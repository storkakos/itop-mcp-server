"""TEST ONLY. Shared values and helpers of the test stack. Every password and secret here is a test value."""
import os
import re
import time
from urllib.parse import urljoin, urlparse

import requests
from bs4 import BeautifulSoup

ITOP = "https://itop.example.com"
SSO = "https://sso.example.com"
CHAT = "https://chat.example.com"
# The MCP server's public URL (its MCP_RESOURCE_URL), group setting TEST_MCP_URL (README "Group settings").
# The only place the test client names it: checks, flows and config edits all use this value. The default
# is the repo stack's; the combined stack, where each repo's server has its own host name, sets the variable.
MCP = os.environ.get("TEST_MCP_URL", "https://mcp.example.com/mcp")
# The same server under a path prefix, behind the README's nginx block for that case. Set only by the
# nginx variant (compose.nginx.yaml); without it the path-prefix check is skipped.
MCP_PREFIX = os.environ.get("TEST_MCP_PREFIX_URL", "")
# The MCP server's audit log as the client sees it (the repo stack mounts the server's log volume read-only).
# Without it the audit-log check is skipped.
AUDIT_LOG = os.environ.get("TEST_MCP_AUDIT_LOG", "")


def metadata_url(resource: str) -> str:
    """Protected resource metadata (RFC 9728): the well-known path goes between origin and the URL's path."""
    u = urlparse(resource)
    return f"{u.scheme}://{u.netloc}/.well-known/oauth-protected-resource{u.path}"


MCP_METADATA = metadata_url(MCP)
# The authorization server the MCP server names: the OAuth extension in iTop.
ISSUER = f"{ITOP}/env-production/altioo-oauth-server"
REALM = "example"
CONFIG = "/var/www/itop/conf/production/config-itop.php"

# Test values
ITOP_ADMIN = ("admin", "Test-Admin-Pw1!")
ITOP_DB = {"host": "db", "user": "itop", "password": "test-itop-db-pw", "database": "itop"}
KC_ADMIN = ("admin", "test-kc-admin-pw")
KC_SECRET_ITOP = "test-secret-itop-client-0123456789"
KC_SECRET_LIBRECHAT = "test-secret-librechat-client-0123456789"
# Local iTop user (prerequisites check 5) and Keycloak users (example checks); Person, profile.
LOCAL_USER = ("lena.local", "Test-Lena-Pw1!", "Lena", "Local", "lena@example.com", "Service Desk Agent")
KC_USERS = [
    ("anna", "Test-Anna-Pw1!", "Anna", "Agent", "anna@example.com", "Service Desk Agent"),
    ("bob", "Test-Bob-Pw1!", "Bob", "Support", "bob@example.com", "Support Agent"),
]
# LibreChat refuses requests without a browser User-Agent ("Illegal request").
BROWSER_UA = "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/130.0.0.0 Safari/537.36"


def say(*a):
    print(*a, flush=True)


def browser() -> requests.Session:
    b = requests.Session()
    b.headers["User-Agent"] = BROWSER_UA
    return b


def page_text(html: str, n: int = 600) -> str:
    return re.sub(r"\s+", " ", BeautifulSoup(html, "lxml").get_text(" ")).strip()[:n]


def follow(b: requests.Session, r, stop_prefix: str | None = None):
    """Follow redirects like a browser; returns the final response, or the URL that starts with stop_prefix."""
    while r.status_code in (301, 302, 303, 307, 308):
        loc = urljoin(r.url, r.headers["Location"])
        if stop_prefix and loc.startswith(stop_prefix):
            return loc
        r = b.get(loc, allow_redirects=False)
    return r


def form_data(form) -> dict:
    data = {}
    for el in form.find_all(["input", "select", "textarea"]):
        name = el.get("name")
        if not name or el.has_attr("disabled"):
            continue
        t = (el.get("type") or "text").lower()
        if el.name == "input" and t in ("checkbox", "radio") and not el.has_attr("checked"):
            continue
        if el.name == "input" and t in ("submit", "button", "image"):
            continue
        if el.name == "select":
            opt = el.find("option", selected=True) or el.find("option")
            data[name] = opt.get("value", opt.text) if opt else ""
        else:
            data[name] = el.get("value", "") if el.name == "input" else el.text
    return data


def wait_for(url: str, ok=lambda r: r.status_code < 500, timeout: int = 900, what: str = ""):
    end = time.time() + timeout
    while True:
        try:
            r = requests.get(url, allow_redirects=False, timeout=10)
            if ok(r):
                return r
        except requests.RequestException:
            pass
        if time.time() > end:
            raise SystemExit(f"timeout waiting for {what or url}")
        time.sleep(3)


def kc_admin() -> requests.Session:
    s = requests.Session()
    tok = s.post(f"{SSO}/realms/master/protocol/openid-connect/token", data={
        "grant_type": "password", "client_id": "admin-cli", "username": KC_ADMIN[0], "password": KC_ADMIN[1]}).json()
    s.headers["Authorization"] = "Bearer " + tok["access_token"]
    return s


def itop_rest(op: dict) -> dict:
    """iTop REST as the test admin (has the REST Services User profile in the test stack)."""
    import json
    r = requests.post(f"{ITOP}/webservices/rest.php", params={"version": "1.3"},
                      data={"auth_user": ITOP_ADMIN[0], "auth_pwd": ITOP_ADMIN[1], "json_data": json.dumps(op)})
    return r.json()
