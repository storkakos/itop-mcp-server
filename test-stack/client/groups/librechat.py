"""TEST ONLY. Check group "librechat": the LibreChat part of the check list of
docs/setup/example-keycloak-librechat.md (checks 5 to 8 and the preselected iTop assistant).
Needs the services librechat and mongo; before its first check it waits until LibreChat answers."""
import os
import time

import requests

import flows
from checklib import Group, Skip
from common import CHAT, KC_USERS, REALM, SSO

# Group settings (see combined-test-stack GLOSSARY): values the group takes from the stack it runs on.
# Defaults are the repo stack's values, so the repo stack behaves as before.
TEST_MCP_URL = os.environ.get("TEST_MCP_URL", "https://mcp.example.com/mcp")
TEST_DEFAULT_SPEC = os.environ.get("TEST_DEFAULT_SPEC", "itop-assistant")

# Seconds to wait for LibreChat before the first check of this group (it boots after the setup).
READY_TIMEOUT = int(os.environ.get("LIBRECHAT_READY_TIMEOUT", "300"))


def wait_for_librechat():
    """LibreChat is ready when /health answers and /api/config offers the Keycloak login. Neither is under
    /oauth/, so the wait costs nothing of LibreChat's login limit."""
    start = time.time()
    last = "no answer"
    while True:
        try:
            if requests.get(f"{CHAT}/health", timeout=10).status_code == 200:
                r = requests.get(f"{CHAT}/api/config", timeout=10)
                if r.status_code == 200 and r.json().get("openidLoginEnabled"):
                    break
                last = f"/api/config answered {r.status_code} without the Keycloak login"
            else:
                last = "/health not 200 yet"
        except (requests.RequestException, ValueError) as e:
            last = type(e).__name__
        if time.time() - start > READY_TIMEOUT:
            raise RuntimeError(f"LibreChat at {CHAT} not ready within {READY_TIMEOUT} s ({last}); is the "
                               "librechat service running? Start the whole stack, or raise LIBRECHAT_READY_TIMEOUT")
        time.sleep(3)
    waited = int(time.time() - start)
    if waited:
        print(f"   waited {waited} s until LibreChat was ready", flush=True)


group = Group(__name__, "Example setup: LibreChat (docs/setup/example-keycloak-librechat.md)", order=40,
              services=("librechat",), ready=wait_for_librechat)
check = group.check
anna, bob = KC_USERS


chats = {}
failed = {}  # user -> why their LibreChat login failed (for another reason than the limit)
skipped = {}  # user -> why their LibreChat login was skipped (LibreChat's login limit)


def _librechat(user):
    lc = flows.LibreChat(user[0], user[1])
    try:
        me = lc.login()
    except Skip as e:
        skipped[user[0]] = str(e)
        raise
    except Exception as e:
        failed[user[0]] = f"{type(e).__name__}: {e}"
        raise
    assert me.get("email") == user[4], me
    chats[user[0]] = lc
    return (f"{me.get('name')} <{me.get('email')}>, PKCE {lc.pkce}, LibreChat login requests left {lc.login_budget}"
            + (f", waited {lc.waited} s for LibreChat's login limit" if lc.waited else ""))


def _chat(user):
    """The LibreChat session of an earlier check. If that login was skipped because of LibreChat's login
    limit, this check is skipped too (with the same reason) instead of failing for lack of a session."""
    if user[0] in skipped:
        raise Skip(f"needs {user[0]}'s LibreChat login, skipped: {skipped[user[0]]}")
    if user[0] in failed:
        raise AssertionError(f"needs {user[0]}'s LibreChat login, which failed: {failed[user[0]]}")
    if user[0] not in chats:
        raise AssertionError(f"needs {user[0]}'s LibreChat login, which has not run (check 5 or 7 not run)")
    return chats[user[0]]


@check("example 5: a Keycloak user logs into LibreChat")
def _():
    return _librechat(anna)


@check("example 6: connecting the itop server opens the iTop consent page")
def _():
    s = _chat(anna).connect_itop()
    if s["consent"]:
        assert "LibreChat MCP Client" in s["consent"] and "iTop assistant" in s["consent"], s["consent"][:300]
    return "connected" + ("" if s["consent"] else " (already authorized earlier)")


@check("example option: iTop assistant preselected for new chats")
def _():
    specs = _chat(anna).config()["modelSpecs"]
    spec = next(x for x in specs["list"] if x["name"] == TEST_DEFAULT_SPEC)
    assert specs.get("prioritize") is True and spec.get("default") is True and spec.get("mcpServers") == ["itop"], specs
    return f"default spec {TEST_DEFAULT_SPEC} with the itop server"


def _whoami_chat(user):
    if not flows.llm_key_present():
        return "SKIP no shared LLM key (LITELLM_KEY in /root/shared/llm.env on the test VM, else test-stack/llm.env), see README"
    lc = _chat(user)
    spec = next(x for x in lc.config()["modelSpecs"]["list"] if x["name"] == TEST_DEFAULT_SPEC)
    calls, text = lc.ask("Use the whoami tool: who am I in iTop?", spec)
    retried = ""
    if not calls and not text.strip():  # the model sometimes answers nothing: ask once more
        print("chat answer empty, retrying once", flush=True)
        retried = " (after one retry: first answer empty)"
        calls, text = lc.ask("Use the whoami tool: who am I in iTop?", spec)
    outputs = " ".join(str(c.get("output")) for c in calls if "whoami" in (c.get("name") or ""))
    assert f"Angemeldet in iTop als: {user[2]} {user[3]}" in outputs, f"tool calls {calls}, answer {text[:200]}"
    return text.strip()[:80] + retried


@check("example 7: whoami names the logged-in iTop user")
def _():
    return _whoami_chat(anna)


@check("example 7: a second user gets their own name")
def _():
    _librechat(bob)
    _chat(bob).connect_itop()
    return _whoami_chat(bob)

@check("example 8: after a LibreChat logout Keycloak asks for a password, and another user logs in")
def _():
    # bob's login follows anna's and his own (check 7). LibreChat counts two requests under /oauth/ per login
    # against LOGIN_MAX (raised in the test stack); if the budget is used up, LibreChat.login waits for the window.
    lc = _chat(bob)
    out = lc.logout()
    assert out["end_session"] == f"{SSO}/realms/{REALM}/protocol/openid-connect/logout", out
    assert out["landed"].startswith(f"{CHAT}/login"), f"after the logout the browser landed on {out['landed']}"
    gone = lc.b.post(f"{CHAT}/api/auth/refresh")
    # Without a session LibreChat answers in plain text ("Refresh token not provided"), with one in JSON.
    assert not (gone.status_code == 200 and gone.headers.get("content-type", "").startswith("application/json")),         "LibreChat session still alive after the logout"
    # The same browser: Sign in with Keycloak must show Keycloak's login form (LibreChat.login asserts it).
    switch = flows.LibreChat(anna[0], anna[1])
    switch.b = lc.b
    me = switch.login()
    assert me.get("email") == anna[4], me
    return (f"Keycloak login form shown again, now {me.get('email')}"
            + (" (Keycloak asked to confirm the logout)" if out["confirmed"] else "")
            + f", LibreChat login requests left {switch.login_budget}"
            + (f", waited {switch.waited} s for LibreChat's login limit" if switch.waited else ""))


@check("example 8: after a LibreChat logout the next user consents in iTop as themselves")
def _():
    import user_switch  # the scenario lives in its own file (combined-stack-findings 09)
    return user_switch.verdict(user_switch.run())
