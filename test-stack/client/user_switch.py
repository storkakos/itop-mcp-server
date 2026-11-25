"""TEST ONLY. User switch in one browser (combined-stack-findings 09).

User A logs into LibreChat and connects the itop server (consent in iTop), then logs out of LibreChat.
User B logs into LibreChat in the same browser and connects the itop server. Expected: iTop no longer
has A's session, so B consents as B and LibreChat gets B's token. Before the fix the iTop session of A
survived the logout, the consent page named A and B's LibreChat got a token for A's iTop account.

    docker compose run --rm client python user_switch.py   # prints each step, exit 1 on the wrong user

checks.py runs the same scenario as one check of the group "librechat" (groups/librechat.py, see run()).
"""
import re
import sys
from collections import Counter

from bs4 import BeautifulSoup

import flows
from common import CHAT, ITOP, KC_USERS, follow, itop_rest, page_text, say


def itop_session(b) -> str | None:
    """Who iTop greets in this browser, or None when iTop shows its login form."""
    r = follow(b, b.get(f"{ITOP}/pages/UI.php", allow_redirects=False))
    if BeautifulSoup(r.text, "lxml").find("form", id="login_form"):
        return None
    hi = re.search(r"Hi ([^!]+)!", page_text(r.text, 5000))
    return hi.group(1) if hi else f"? ({r.status_code} {r.url})"


def grants() -> Counter:
    """altioo-oauth-server's connections (AltiooOAuthGrant), counted per iTop login."""
    res = itop_rest({"operation": "core/get", "class": "AltiooOAuthGrant", "key": "SELECT AltiooOAuthGrant",
                     "output_fields": "user_id_friendlyname"})
    assert res.get("code") == 0, f"iTop REST: {res.get('message')}"
    return Counter(o["fields"]["user_id_friendlyname"] for o in (res.get("objects") or {}).values())


def consenting_login(consent_text: str | None) -> str | None:
    """The account the consent page names ("... wants to act as <login> on this iTop.")."""
    m = re.search(r"wants to act as (\S+) on this iTop", consent_text or "")
    return m.group(1) if m else None


def disconnect(lc) -> None:
    """LibreChat's Disconnect of the itop server: forgets the stored token, so the next connect opens iTop."""
    r = lc.b.post(f"{CHAT}/api/user/plugins", headers=lc.h,
                  json={"pluginKey": "mcp_itop", "action": "uninstall", "auth": {}})
    assert r.status_code < 400, f"LibreChat disconnect {r.status_code} {r.text[:200]}"


def run(a=KC_USERS[0], b=KC_USERS[1], log=lambda *_: None) -> dict:
    """The scenario, step by step. Returns what B ended up with; log(step, result) gets every step."""
    lc_a = flows.LibreChat(a[0], a[1])
    me = lc_a.login()
    log("1. A logs into LibreChat", me.get("email"))
    disconnect(lc_a)
    s = lc_a.connect_itop()
    log("2. A connects itop: consent page names", consenting_login(s["consent"]) or "(no consent page)")
    log("   iTop session in the browser", itop_session(lc_a.b))
    out = lc_a.logout()
    log("3. A logs out of LibreChat", f"landed on {out['landed']}, front-channel logouts {out['frontchannel']}")
    after_logout = itop_session(lc_a.b)
    log("4. iTop session in the browser after the logout", after_logout or "none (iTop login form)")

    lc_b = flows.LibreChat(b[0], b[1])
    lc_b.b = lc_a.b  # the same browser
    me = lc_b.login()
    log("5. B logs into LibreChat in the same browser", me.get("email"))
    disconnect(lc_b)
    before = grants()
    s = lc_b.connect_itop()
    consented_as = consenting_login(s["consent"])
    log("6. B connects itop: consent page names", consented_as or "(no consent page)")
    log("   consent page text", (s["consent"] or "")[:420])
    new = grants() - before
    log("7. new iTop connection (the token B's LibreChat holds) belongs to", dict(new))
    return {"itop_after_logout": after_logout, "consented_as": consented_as, "token_for": list(new),
            "budget": lc_b.login_budget, "waited": lc_a.waited + lc_b.waited}


def verdict(res: dict, b=KC_USERS[1]) -> str:
    """Raises AssertionError when B consented or got a token as someone else."""
    assert res["consented_as"] == b[4], \
        f"B ({b[4]}) was shown the consent page for {res['consented_as']} (iTop session after logout: " \
        f"{res['itop_after_logout']})"
    assert res["token_for"] == [b[4]], f"B's LibreChat holds a token for {res['token_for']}"
    return (f"consent and token for {b[4]}, iTop session after the logout: {res['itop_after_logout'] or 'none'}"
            + (f", waited {res['waited']} s for LibreChat's login limit" if res["waited"] else ""))


if __name__ == "__main__":
    result = run(log=lambda step, value: say(f"{step}: {value}"))
    try:
        say("PASS", verdict(result))
    except AssertionError as e:
        say("FAIL", e)
        sys.exit(1)
