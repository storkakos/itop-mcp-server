"""TEST ONLY. Check group "example": the Keycloak and iTop part of the check list of
docs/setup/example-keycloak-librechat.md (checks 1 to 4, and the Keycloak setup run again).
No LibreChat needed; the LibreChat checks are the group "librechat"."""
from urllib.parse import urlparse

import requests
from bs4 import BeautifulSoup

import flows
import keycloak_realm
from checklib import Group
from common import CHAT, ITOP, KC_USERS, REALM, SSO, browser, follow, kc_admin, page_text

group = Group(__name__, "Example setup: Keycloak and iTop (docs/setup/example-keycloak-librechat.md)", order=30)
check = group.check
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
