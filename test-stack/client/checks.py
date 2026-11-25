"""TEST ONLY. Runs the check lists of docs/setup/itop-prerequisites.md and docs/setup/example-keycloak-librechat.md
against the test stack and reports each check as PASS, FAIL or SKIP. Exit code 1 if any check failed.

    docker compose run --rm client python checks.py
"""
import re
import sys
import traceback
from pathlib import Path
from urllib.parse import urlparse

import requests
from bs4 import BeautifulSoup

import flows
import keycloak_realm
from common import (CHAT, CONFIG, ITOP, KC_USERS, LOCAL_USER, MCP, MCP_METADATA, MCP_PREFIX, REALM, SSO, browser, follow,
                    kc_admin, metadata_url, page_text)

results = []


def check(name):
    def deco(fn):
        try:
            detail = fn()
            if detail == "SKIP" or (isinstance(detail, str) and detail.startswith("SKIP")):
                results.append(("SKIP", name, detail[5:]))
            else:
                results.append(("PASS", name, detail or ""))
        except Exception as e:  # noqa: BLE001
            results.append(("FAIL", name, f"{type(e).__name__}: {e}"))
            if "-v" in sys.argv:
                traceback.print_exc()
        status, _, detail = results[-1]
        print(f"{status}  {name}" + (f"  ({detail})" if detail else ""), flush=True)
        return fn
    return deco


ISSUER = f"{ITOP}/env-production/altioo-oauth-server"
print("== iTop prerequisites (docs/setup/itop-prerequisites.md)")


@check("prerequisites 1: authorization server metadata at the site root")
def _():
    d = requests.get(f"{ITOP}/.well-known/oauth-authorization-server/env-production/altioo-oauth-server").json()
    assert d["issuer"] == ISSUER, d["issuer"]
    for k in ("authorization_endpoint", "token_endpoint", "registration_endpoint"):
        assert d.get(k), k


@check("prerequisites 2: MCP server answers 401 with resource_metadata")
def _():
    r = requests.post(MCP, json={"jsonrpc": "2.0", "id": 1, "method": "initialize", "params": {}},
                      headers={"Accept": "application/json, text/event-stream"})
    assert r.status_code == 401, r.status_code
    assert f'resource_metadata="{MCP_METADATA}"' in r.headers["www-authenticate"], r.headers["www-authenticate"]


@check("prerequisites 3: protected-resource metadata points at iTop")
def _():
    d = requests.get(MCP_METADATA).json()
    assert d["resource"] == MCP and d["authorization_servers"] == [ISSUER], d


@check("prerequisites 4: resource URL identical in MCP server, metadata and config-itop.php")
def _():
    d = requests.get(MCP_METADATA).json()
    m = re.search(r"'itop-mcp' => array\(.*?'url' => '([^']+)'", Path(CONFIG).read_text(), re.S)
    assert m and m.group(1) == d["resource"] == MCP, (m and m.group(1), d["resource"])


@check("prerequisites 5: MCP client connects (iTop login form, consent, whoami)")
def _():
    answer = flows.mcp_oauth_flow("form", LOCAL_USER[0], LOCAL_USER[1])
    assert f"{LOCAL_USER[2]} {LOCAL_USER[3]}" in answer, answer
    return answer


@check("prerequisites: extension directory is private except index.php")
def _():
    for p in ("README.md", "src/", "vendor/autoload.php"):
        code = requests.get(f"{ISSUER}/{p}").status_code
        assert code in (403, 404), f"{p}: {code}"


print("== Reverse proxy (README.md)")


@check("README: MCP server and its metadata under a path prefix (nginx)")
def _():
    if not MCP_PREFIX:
        return "SKIP only in the nginx variant (compose.nginx.yaml)"
    meta = metadata_url(MCP_PREFIX)
    r = requests.post(MCP_PREFIX, json={"jsonrpc": "2.0", "id": 1, "method": "initialize", "params": {}},
                      headers={"Accept": "application/json, text/event-stream"})
    assert r.status_code == 401, r.status_code
    assert f'resource_metadata="{meta}"' in r.headers["www-authenticate"], r.headers["www-authenticate"]
    d = requests.get(meta).json()
    assert d["resource"] == MCP_PREFIX and d["authorization_servers"] == [ISSUER], d
    answer = flows.mcp_call(flows.mcp_token("form", LOCAL_USER[0], LOCAL_USER[1]), "whoami", MCP_PREFIX)
    assert f"{LOCAL_USER[2]} {LOCAL_USER[3]}" in answer, answer
    return MCP_PREFIX


print("== Example setup (docs/setup/example-keycloak-librechat.md)")
anna, bob = KC_USERS


@check("example 1: Keycloak realm answers")
def _():
    d = requests.get(f"{SSO}/realms/{REALM}/.well-known/openid-configuration").json()
    assert d["issuer"] == f"{SSO}/realms/{REALM}", d["issuer"]
    assert d["authorization_endpoint"].endswith("/protocol/openid-connect/auth")


@check("example 2: iTop's login page offers Keycloak")
def _():
    b = browser()
    r = follow(b, b.get(f"{ITOP}/", allow_redirects=False))
    assert "Sign in with Keycloak" in r.text and BeautifulSoup(r.text, "lxml").find("form", id="login_form")


@check("example 3: a Keycloak user logs into iTop")
def _():
    name = flows.itop_keycloak_login(anna[0], anna[1])
    assert name == anna[2], name
    return f"Hi {name}!"


@check("example 3: the user cannot change their email")
def _():
    import base64, hashlib, secrets
    from urllib.parse import parse_qs
    b = browser()
    kc = f"{SSO}/realms/{REALM}"
    verifier = secrets.token_urlsafe(48)
    ch = base64.urlsafe_b64encode(hashlib.sha256(verifier.encode()).digest()).rstrip(b"=").decode()
    r = b.get(f"{kc}/protocol/openid-connect/auth", params={
        "client_id": "account-console", "redirect_uri": f"{kc}/account/", "response_type": "code",
        "scope": "openid", "code_challenge": ch, "code_challenge_method": "S256", "state": "x"})
    form = BeautifulSoup(r.text, "lxml").find("form", id="kc-form-login")
    r = b.post(form["action"], data={"username": anna[0], "password": anna[1], "credentialId": ""}, allow_redirects=False)
    code = parse_qs(urlparse(r.headers["Location"]).query)["code"][0]
    tok = b.post(f"{kc}/protocol/openid-connect/token", data={
        "grant_type": "authorization_code", "client_id": "account-console", "code": code,
        "redirect_uri": f"{kc}/account/", "code_verifier": verifier}).json()["access_token"]
    h = {"Authorization": "Bearer " + tok, "Accept": "application/json"}
    me = b.get(f"{kc}/account/?userProfileMetadata=true", headers=h).json()
    meta = next(a for a in me["userProfileMetadata"]["attributes"] if a["name"] == "email")
    assert meta.get("readOnly") is True, "Email is editable"
    body = {k: me[k] for k in ("username", "firstName", "lastName", "email")}
    body["email"] = "anna.changed@example.com"
    r = b.post(f"{kc}/account/", headers=h, json=body)
    assert b.get(f"{kc}/account/", headers=h).json()["email"] == anna[4], "email was changed"
    return f"change refused with {r.status_code}"


@check("example 3: a second user with the same email and an unverified email do not get through")
def _():
    adm = kc_admin()
    A = f"{SSO}/admin/realms/{REALM}"
    r = adm.post(f"{A}/users", json={"username": "dup", "email": anna[4], "enabled": True})
    assert r.status_code == 409, f"duplicate email accepted: {r.status_code}"
    adm.post(f"{A}/users", json={"username": "unverified", "email": "unverified@example.com", "emailVerified": False,
                                 "enabled": True, "credentials": [{"type": "password", "value": "Test-Unv-Pw1!",
                                                                    "temporary": False}]})
    try:
        b = browser()
        r = follow(b, b.get(f"{ITOP}/", allow_redirects=False))
        r = flows._keycloak_button(b, r)
        form = BeautifulSoup(r.text, "lxml").find("form", id="kc-form-login")
        r = follow(b, b.post(form["action"], data={"username": "unverified", "password": "Test-Unv-Pw1!",
                                                   "credentialId": ""}, allow_redirects=False), ITOP)
        assert not isinstance(r, str) and "verify your email" in page_text(r.text, 2000).lower(), \
            "unverified user got through"
        mails = requests.get("http://mail:8025/api/v1/messages").json()["messages"]
        assert any(t["Address"] == "unverified@example.com" for m in mails for t in m["To"]), "no verification mail"
    finally:
        for u in adm.get(f"{A}/users", params={"username": "unverified", "exact": "true"}).json():
            adm.delete(f"{A}/users/{u['id']}")


@check("example 4: MCP OAuth flow through Keycloak to the consent page")
def _():
    answer = flows.mcp_oauth_flow("keycloak", anna[0], anna[1])
    assert f"{anna[2]} {anna[3]}" in answer, answer
    return answer


chats = {}


def _librechat(user):
    lc = flows.LibreChat(user[0], user[1])
    me = lc.login()
    assert me.get("email") == user[4], me
    chats[user[0]] = lc
    return f"{me.get('name')} <{me.get('email')}>, PKCE {lc.pkce}, LibreChat login requests left {lc.login_budget}"


@check("example 5: a Keycloak user logs into LibreChat")
def _():
    return _librechat(anna)


@check("example 6: connecting the itop server opens the iTop consent page")
def _():
    s = chats[anna[0]].connect_itop()
    if s["consent"]:
        assert "LibreChat MCP Client" in s["consent"] and "iTop assistant" in s["consent"], s["consent"][:300]
    return "connected" + ("" if s["consent"] else " (already authorized earlier)")


@check("example option: iTop assistant preselected for new chats")
def _():
    specs = chats[anna[0]].config()["modelSpecs"]
    spec = next(x for x in specs["list"] if x["name"] == "itop-assistant")
    assert specs.get("prioritize") is True and spec.get("default") is True and spec.get("mcpServers") == ["itop"], specs
    return "default spec itop-assistant with the itop server"


def _whoami_chat(user):
    if not flows.llm_key_present():
        return "SKIP no shared LLM key (/root/shared/llm.env on the test VM, else test-stack/llm.env), see README"
    lc = chats[user[0]]
    spec = next(x for x in lc.config()["modelSpecs"]["list"] if x["name"] == "itop-assistant")
    calls, text = lc.ask("Use the whoami tool: who am I in iTop?", spec)
    outputs = " ".join(str(c.get("output")) for c in calls if "whoami" in (c.get("name") or ""))
    assert f"Angemeldet in iTop als: {user[2]} {user[3]}" in outputs, f"tool calls {calls}, answer {text[:200]}"
    return text.strip()[:80]


@check("example 7: whoami names the logged-in iTop user")
def _():
    return _whoami_chat(anna)


@check("example 7: a second user gets their own name")
def _():
    _librechat(bob)
    chats[bob[0]].connect_itop()
    return _whoami_chat(bob)


@check("example setup: running the Keycloak setup again keeps client settings it does not own")
def _():
    # Another stack's or an admin's settings on the librechat client, then the stack's own setup again.
    kc = kc_admin()
    base = f"{SSO}/admin/realms/{REALM}/clients"
    url = f"{base}/{kc.get(base, params={'clientId': 'librechat'}).json()[0]['id']}"
    other = "https://other.example.com"
    rep = kc.get(url).json()
    rep["attributes"]["test.foreign.attribute"] = "kept"
    rep["attributes"]["post.logout.redirect.uris"] += f"##{other}/login"
    rep["redirectUris"] = rep["redirectUris"] + [f"{other}/callback"]
    assert kc.put(url, json=rep).status_code == 204
    try:
        keycloak_realm.setup_realm()
        after = kc.get(url).json()
        logout_uris = after["attributes"].get("post.logout.redirect.uris", "").split("##")
        assert after["attributes"].get("test.foreign.attribute") == "kept", after["attributes"]
        assert f"{other}/login" in logout_uris and f"{CHAT}/login" in logout_uris, logout_uris
        assert f"{other}/callback" in after["redirectUris"]             and f"{CHAT}/oauth/openid/callback" in after["redirectUris"], after["redirectUris"]
    finally:  # back to the stack's own settings
        rep = kc.get(url).json()
        rep["attributes"]["test.foreign.attribute"] = ""  # an empty value removes the attribute
        rep["attributes"]["post.logout.redirect.uris"] = "##".join(
            x for x in rep["attributes"]["post.logout.redirect.uris"].split("##") if not x.startswith(other))
        rep["redirectUris"] = [x for x in rep["redirectUris"] if not x.startswith(other)]
        kc.put(url, json=rep)
    return "foreign attribute, redirect URI and post-logout redirect URI kept next to the stack's own"


@check("example 8: after a LibreChat logout Keycloak asks for a password, and another user logs in")
def _():
    # bob's login follows anna's and his own (check 7). LibreChat counts two requests under /oauth/ per login
    # against its limit of 7 per 5 minutes; if the budget is used up, LibreChat.login waits for the window.
    lc = chats[bob[0]]
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


failed = [r for r in results if r[0] == "FAIL"]
print(f"\n{sum(r[0] == 'PASS' for r in results)} passed, {len(failed)} failed, "
      f"{sum(r[0] == 'SKIP' for r in results)} skipped")
sys.exit(1 if failed else 0)
