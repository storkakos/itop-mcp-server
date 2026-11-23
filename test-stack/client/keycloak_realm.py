"""TEST ONLY. The example manual's Keycloak steps through the admin REST API.

Same values as the admin-console tables in docs/setup/example-keycloak-librechat.md. Differences for
the local test, each on purpose: the realm itself (the manual assumes it exists) with Mailpit as SMTP;
fixed client secrets (test values) instead of copying them from the Credentials tab.
"""
from common import CHAT, ITOP, KC_SECRET_ITOP, KC_SECRET_LIBRECHAT, KC_USERS, REALM, SSO, kc_admin, say


def _ok(r):
    if r.status_code >= 400:
        raise SystemExit(f"{r.request.method} {r.url}: {r.status_code} {r.text[:300]}")
    return r


def setup_realm() -> None:
    s = kc_admin()
    A = f"{SSO}/admin/realms"
    if s.get(f"{A}/{REALM}").status_code == 404:
        _ok(s.post(A, json={"realm": REALM, "enabled": True,
                            "smtpServer": {"host": "mail", "port": "1025", "from": "keycloak@example.com"}}))
    R = f"{A}/{REALM}"

    def client(cid, name, root, redirect, secret):
        body = {
            "clientId": cid, "name": name, "protocol": "openid-connect", "enabled": True,
            "publicClient": False, "clientAuthenticatorType": "client-secret", "secret": secret,
            "authorizationServicesEnabled": False, "standardFlowEnabled": True,
            "directAccessGrantsEnabled": False, "implicitFlowEnabled": False, "serviceAccountsEnabled": False,
            "attributes": {"standard.token.exchange.enabled": "false",
                           "oauth2.device.authorization.grant.enabled": "false",
                           "oidc.ciba.grant.enabled": "false", "pkce.code.challenge.method": "",
                           "post.logout.redirect.uris": ""},
            "rootUrl": root, "baseUrl": root + "/", "redirectUris": [redirect], "webOrigins": [],
        }
        found = s.get(f"{R}/clients", params={"clientId": cid}).json()
        if found:
            _ok(s.put(f"{R}/clients/{found[0]['id']}", json=body))
        else:
            _ok(s.post(f"{R}/clients", json=body))
        say("   keycloak client", cid)

    client("itop", "iTop", ITOP, f"{ITOP}/env-production/combodo-hybridauth/landing.php", KC_SECRET_ITOP)
    client("librechat", "LibreChat", CHAT, f"{CHAT}/oauth/openid/callback", KC_SECRET_LIBRECHAT)

    # "Lock down the email in the realm"
    up = _ok(s.get(f"{R}/users/profile")).json()
    next(a for a in up["attributes"] if a["name"] == "email")["permissions"]["edit"] = ["admin"]
    _ok(s.put(f"{R}/users/profile", json=up))
    realm = s.get(R).json()
    realm.update({"verifyEmail": True, "duplicateEmailsAllowed": False, "registrationAllowed": False,
                  "editUsernameAllowed": False})
    _ok(s.put(R, json=realm))
    say("   keycloak email lock-down")

    for username, pw, first, last, mail, _profile in KC_USERS:
        if not s.get(f"{R}/users", params={"username": username, "exact": "true"}).json():
            _ok(s.post(f"{R}/users", json={
                "username": username, "firstName": first, "lastName": last, "email": mail,
                "emailVerified": True, "enabled": True,
                "credentials": [{"type": "password", "value": pw, "temporary": False}]}))
        say("   keycloak user", username, mail)
