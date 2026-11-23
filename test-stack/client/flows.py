"""TEST ONLY. Browser flows: MCP OAuth through iTop (form or Keycloak login), LibreChat login, connect, chat."""
import base64
import hashlib
import json
import os
import re
import secrets
import time
import uuid
from urllib.parse import parse_qs, urljoin, urlparse

import requests
from bs4 import BeautifulSoup

from common import CHAT, ITOP, MCP, browser, follow, form_data, page_text, say

CALLBACK = f"{CHAT}/api/mcp/itop/oauth/callback"


def _keycloak_button(b, r):
    """Clicks "Sign in with Keycloak" on iTop's login page (the button submits the login form via JS)."""
    m = re.search(r"\$\('#login_mode'\)\.val\('(hybridauth-[^']+)'\)", r.text)
    if not (m and "Sign in with Keycloak" in r.text):
        raise AssertionError("no 'Sign in with Keycloak' button on iTop's login page")
    return follow(b, b.post(r.url, data={"login_mode": m.group(1), "loginop": "login"}, allow_redirects=False), CALLBACK)


def _keycloak_login(b, r, user, pwd):
    form = BeautifulSoup(r.text, "lxml").find("form", id="kc-form-login")
    return follow(b, b.post(form["action"], data={"username": user, "password": pwd, "credentialId": ""},
                            allow_redirects=False), CALLBACK)


def browse_to_consent(b, r, login, user, pwd, stop_on_home=False):
    """Walks login pages until the consent page, the client callback, or (stop_on_home) iTop's home page."""
    for _ in range(10):
        if isinstance(r, str):
            return "callback", r
        soup = BeautifulSoup(r.text, "lxml")
        host = urlparse(r.url).netloc
        if host == "itop.example.com" and soup.find("form", id="login_form"):
            if login == "form":
                r = follow(b, b.post(r.url, data={"auth_user": user, "auth_pwd": pwd, "login_mode": "form",
                                                  "loginop": "login"}, allow_redirects=False), CALLBACK)
            else:
                r = _keycloak_button(b, r)
        elif host == "sso.example.com" and soup.find("form", id="kc-form-login"):
            r = _keycloak_login(b, r, user, pwd)
        elif host == "itop.example.com" and "altioo-oauth-server" in r.url and soup.find("form"):
            return "consent", r
        elif host == "itop.example.com" and "/pages/UI.php" in r.url:
            if stop_on_home:
                return "home", r
            raise AssertionError("landed on iTop's home page instead of the consent page")
        else:
            return "other", r
    raise AssertionError("too many pages")


def consent(b, r):
    form = BeautifulSoup(r.text, "lxml").find("form")
    d = form_data(form)
    d["decision"] = "allow"
    return follow(b, b.post(urljoin(r.url, form.get("action") or r.url), data=d, allow_redirects=False), CALLBACK)


def mcp_call(token: str, tool: str) -> str:
    c = requests.Session()
    h = {"Authorization": f"Bearer {token}", "Accept": "application/json, text/event-stream"}
    r = c.post(MCP, headers=h, json={"jsonrpc": "2.0", "id": 1, "method": "initialize", "params": {
        "protocolVersion": "2025-06-18", "capabilities": {}, "clientInfo": {"name": "test-stack", "version": "1"}}})
    r.raise_for_status()
    if r.headers.get("mcp-session-id"):
        h["mcp-session-id"] = r.headers["mcp-session-id"]
    r = c.post(MCP, headers=h, json={"jsonrpc": "2.0", "id": 2, "method": "tools/call",
                                      "params": {"name": tool, "arguments": {}}})
    m = re.search(r"data: (.*)", r.text)
    body = json.loads(m.group(1)) if m else r.json()
    return body["result"]["content"][0]["text"]


def mcp_oauth_flow(login: str, user: str, pwd: str) -> str:
    """An MCP client like LibreChat: discovery, registration, login, consent, token, whoami. Returns whoami."""
    c = requests.Session()
    r = c.post(MCP, json={"jsonrpc": "2.0", "id": 1, "method": "initialize", "params": {}},
               headers={"Accept": "application/json, text/event-stream"})
    assert r.status_code == 401, r.status_code
    prm = c.get(re.search(r'resource_metadata="([^"]+)"', r.headers["www-authenticate"]).group(1)).json()
    u = urlparse(prm["authorization_servers"][0])
    asm = c.get(f"{u.scheme}://{u.netloc}/.well-known/oauth-authorization-server{u.path}").json()
    reg = c.post(asm["registration_endpoint"], json={
        "client_name": "test-stack client", "redirect_uris": [CALLBACK], "token_endpoint_auth_method": "none",
        "grant_types": ["authorization_code", "refresh_token"], "response_types": ["code"]})
    assert reg.status_code in (200, 201), f"registration {reg.status_code} {reg.text[:200]}"
    client_id = reg.json()["client_id"]
    verifier = secrets.token_urlsafe(48)
    challenge = base64.urlsafe_b64encode(hashlib.sha256(verifier.encode()).digest()).rstrip(b"=").decode()
    state = secrets.token_urlsafe(16)
    b = browser()
    r = follow(b, b.get(asm["authorization_endpoint"], params={
        "response_type": "code", "client_id": client_id, "redirect_uri": CALLBACK, "state": state,
        "code_challenge": challenge, "code_challenge_method": "S256", "resource": prm["resource"],
        "scope": "REST/JSON"}, allow_redirects=False), CALLBACK)
    where, r = browse_to_consent(b, r, login, user, pwd)
    assert where == "consent", f"expected the consent page, got {where}: {getattr(r, 'url', r)}"
    assert "iTop assistant" in r.text, page_text(r.text, 300)
    cb = consent(b, r)
    assert isinstance(cb, str), "consent did not lead back to the client"
    q = parse_qs(urlparse(cb).query)
    assert q.get("state") == [state]
    tok = c.post(asm["token_endpoint"], data={
        "grant_type": "authorization_code", "code": q["code"][0], "redirect_uri": CALLBACK,
        "client_id": client_id, "code_verifier": verifier, "resource": prm["resource"]})
    assert tok.status_code == 200, tok.text[:200]
    return mcp_call(tok.json()["access_token"], "whoami")


def itop_keycloak_login(user: str, pwd: str) -> str:
    """Example check 3: Keycloak login into iTop. Returns the name iTop greets."""
    b = browser()
    r = follow(b, b.get(f"{ITOP}/", allow_redirects=False))
    where, r = browse_to_consent(b, r, "keycloak", user, pwd, stop_on_home=True)
    assert where == "home", f"expected iTop's home page, got {where}"
    hi = re.search(r"Hi ([^!]+)!", page_text(r.text, 5000))
    assert hi, "not logged in"
    return hi.group(1)


class LibreChat:
    """A LibreChat user in a browser."""

    def __init__(self, user: str, pwd: str):
        self.b = browser()
        self.user, self.pwd = user, pwd
        self.h: dict = {}

    def login(self) -> dict:
        cfg = self.b.get(f"{CHAT}/api/config").json()
        assert cfg.get("openidLoginEnabled"), "no Sign in with Keycloak in LibreChat"
        r = self.b.get(f"{CHAT}/oauth/openid", allow_redirects=False)
        q = parse_qs(urlparse(r.headers.get("Location", "")).query)
        self.pkce = q.get("code_challenge_method", [None])[0]
        r = follow(self.b, r)
        r = _keycloak_login(self.b, r, self.user, self.pwd)
        if "error=" in getattr(r, "url", ""):
            raise AssertionError(f"LibreChat login failed: {r.url}")
        tok = self.b.post(f"{CHAT}/api/auth/refresh")
        assert tok.status_code == 200 and tok.headers.get("content-type", "").startswith("application/json"), \
            f"no LibreChat session: {tok.status_code} {tok.text[:150]}"
        self.h = {"Authorization": "Bearer " + tok.json()["token"]}
        return tok.json()["user"]

    def config(self) -> dict:
        return self.b.get(f"{CHAT}/api/config", headers=self.h).json()

    def connect_itop(self) -> dict:
        r = self.b.post(f"{CHAT}/api/mcp/itop/reinitialize", headers=self.h, json={})
        data = r.json()
        consent_text = None
        if data.get("oauthUrl"):
            r = follow(self.b, self.b.get(data["oauthUrl"], allow_redirects=False), CALLBACK)
            where, r = browse_to_consent(self.b, r, "keycloak", self.user, self.pwd)
            assert where == "consent", f"expected the consent page, got {where}"
            consent_text = page_text(r.text, 3000)
            cb = consent(self.b, r)
            assert isinstance(cb, str)
            self.b.get(cb)  # the browser opens LibreChat's callback
        for _ in range(15):
            st = self.b.get(f"{CHAT}/api/mcp/connection/status", headers=self.h).json()
            s = st.get("connectionStatus", {}).get("itop", {})
            if s.get("connectionState") == "connected":
                return {"consent": consent_text, **s}
            time.sleep(1)
        raise AssertionError(f"itop not connected: {s}")

    def ask(self, question: str, spec: dict) -> tuple[list, str]:
        """New chat with the given model spec; returns (tool calls, answer text)."""
        preset = spec["preset"]
        body = {
            "text": question, "sender": "User", "isCreatedByUser": True,
            "parentMessageId": "00000000-0000-0000-0000-000000000000", "conversationId": None,
            "messageId": str(uuid.uuid4()), "error": False, "endpoint": preset["endpoint"],
            "endpointType": "custom", "model": preset["model"], "spec": spec["name"], "key": None,
            "isContinued": False, "isTemporary": False,
            "ephemeralAgent": {"mcp": spec.get("mcpServers", []), "execute_code": False, "web_search": False,
                               "file_search": False},
        }
        r = self.b.post(f"{CHAT}/api/agents/chat/{preset['endpoint']}", headers=self.h, json=body)
        d = r.json()
        r = self.b.get(f"{CHAT}/api/agents/chat/stream/{d['streamId']}", headers=self.h, stream=True, timeout=180)
        final = None
        for line in r.iter_lines(decode_unicode=True):
            if line and line.startswith("data:"):
                try:
                    ev = json.loads(line[5:].strip())
                except json.JSONDecodeError:
                    continue
                if ev.get("final"):
                    final = ev
                    break
        msg = (final or {}).get("responseMessage") or {}
        parts = msg.get("content") or []
        calls = [p["tool_call"] for p in parts if p.get("type") == "tool_call"]
        text = (msg.get("text") or "") + "".join(p.get("text", "") for p in parts if p.get("type") == "text")
        return calls, text


def llm_key_present() -> bool:
    return any(v for k, v in os.environ.items() if k.endswith("_KEY") and k != "REQUESTS_CA_BUNDLE")
