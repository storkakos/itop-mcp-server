"""TEST ONLY. Check group "consent": what the docs say about iTop's consent page and menus, compared with
a running iTop. Logs in to iTop's own login form (admin), never through LibreChat, so it does not use
LibreChat's login limit, and needs only the setup's part of the stack.

- The consent page for an account without the needed profile has the wording the docs quote.
- The iTop menu paths the docs name exist for an administrator."""
import base64
import hashlib
import os
import re
import secrets
from pathlib import Path

import requests
from bs4 import BeautifulSoup

import flows
from checklib import Group
from common import ITOP, ITOP_ADMIN, MCP, browser, follow, page_text

group = Group(__name__, "Consent page wording and iTop menu paths of the docs, checked against iTop", order=15)
check = group.check

# The docs, mounted read-only into the client container (compose.yaml).
DOCS = Path(os.environ.get("TEST_DOCS", "/docs"))
WORDING_DOCS = ["README.md", "docs/setup/itop-prerequisites.md", "docs/setup/example-keycloak-librechat.md"]
MENU_DOCS = WORDING_DOCS + ["docs/quick-start.md"]
HEADLINE = "Not available for your account"


def _doc(rel: str) -> str:
    return re.sub(r"\s+", " ", (DOCS / rel).read_text(encoding="utf-8"))


def _consent_page_without_profile() -> str:
    """Page text the consent URL shows to the test admin, who by design lacks the profiles of the MCP resource."""
    c = requests.Session()
    asm = c.get(f"{ITOP}/.well-known/oauth-authorization-server/env-production/altioo-oauth-server").json()
    reg = c.post(asm["registration_endpoint"], json={
        "client_name": "test-stack consent check", "redirect_uris": [flows.CALLBACK],
        "token_endpoint_auth_method": "none", "grant_types": ["authorization_code"], "response_types": ["code"]})
    assert reg.status_code in (200, 201), f"registration {reg.status_code} {reg.text[:200]}"
    verifier = secrets.token_urlsafe(48)
    challenge = base64.urlsafe_b64encode(hashlib.sha256(verifier.encode()).digest()).rstrip(b"=").decode()
    b = browser()
    r = follow(b, b.get(asm["authorization_endpoint"], params={
        "response_type": "code", "client_id": reg.json()["client_id"], "redirect_uri": flows.CALLBACK,
        "state": "x", "code_challenge": challenge, "code_challenge_method": "S256", "resource": MCP,
        "scope": "REST/JSON"}, allow_redirects=False), flows.CALLBACK)
    where, r = flows.browse_to_consent(b, r, "form", ITOP_ADMIN[0], ITOP_ADMIN[1])
    assert where in ("consent", "other"), f"expected a page of iTop, got {where}"
    assert not isinstance(r, str), "the account without the profile was sent back to the client"
    form = BeautifulSoup(r.text, "lxml").find("form")
    assert not (form and form.find("input", {"name": "decision"})), \
        "consent was offered to an account without the profile: " + page_text(r.text, 300)
    return page_text(r.text, 3000)


@check("consent: the page for an account without the profile says what README, prerequisites and example quote")
def _():
    text = _consent_page_without_profile()
    low = text.lower()
    quoted = []
    for rel in WORDING_DOCS:
        doc = _doc(rel)
        assert f'"{HEADLINE}"' in doc, f"{rel} does not quote \"{HEADLINE}\" (was the wording removed?)"
        quoted.append((rel, HEADLINE))
        # the second sentence follows the headline in README and prerequisites: "Headline" – "Sentence"
        for m in re.finditer(rf'"{HEADLINE}"\s*[–-]\s*"([^"]+)"', doc):
            quoted.append((rel, m.group(1)))
    assert any(q != HEADLINE for _, q in quoted), "no doc quotes the sentence below the headline"
    wrong = [f"{rel}: \"{q}\"" for rel, q in quoted if q.rstrip(".! ").lower() not in low]
    assert not wrong, "docs quote wording the consent page does not show: " + "; ".join(wrong) + f" | page: {text[:400]}"
    return f"{len(quoted)} quotes in {len(WORDING_DOCS)} docs found on the page"


def _admin_menu() -> list:
    """Menu labels of iTop's navigation as an administrator sees them, in page order."""
    b = browser()
    r = follow(b, b.get(f"{ITOP}/", allow_redirects=False))
    where, r = flows.browse_to_consent(b, r, "form", ITOP_ADMIN[0], ITOP_ADMIN[1], stop_on_home=True)
    assert where == "home", f"expected iTop's home page, got {where}"
    soup = BeautifulSoup(r.text, "lxml")
    nav = soup.select_one(".ibo-navigation-menu") or soup
    labels = [re.sub(r"\s+", " ", t).strip() for t in nav.stripped_strings]
    assert "Administration" in labels, f"no 'Administration' in the menu: {labels[:40]}"
    return labels


def _documented_paths() -> list:
    """Menu chains from the docs: '*Administration* → *User management* → *User accounts* → *New* → ...' up to the first action."""
    paths = set()
    for rel in MENU_DOCS:
        for m in re.finditer(r"Administration[*]* (?:→ [*]*[^*→|.(),]+[*]* ?)+", _doc(rel).replace("*", "")):
            parts = [p.strip() for p in m.group(0).split("→")]
            for stop in ("New", "the user"):  # an action or a record, not a menu entry
                if stop in parts:
                    parts = parts[:parts.index(stop)]
            paths.add(tuple(parts))
    return sorted(paths)


@check("consent: the menu paths the docs name exist for an administrator, including Profiles under User management")
def _():
    labels = _admin_menu()
    paths = _documented_paths()
    assert paths, "found no 'Administration → ...' path in the docs"
    paths = sorted(set(paths) | {("Administration", "User management", "Profiles")})
    missing = []
    for path in paths:
        pos = -1
        for item in path:
            try:
                pos = labels.index(item, pos + 1)
            except ValueError:
                missing.append(" → ".join(path) + f" (no '{item}')")
                break
    assert not missing, "menu path not in iTop: " + "; ".join(missing) + f" | menu: {labels[:60]}"
    return "; ".join(" → ".join(p) for p in paths)
