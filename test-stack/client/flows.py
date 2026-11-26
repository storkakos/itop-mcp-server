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

from checklib import Skip
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


def mcp_call(token: str, tool: str, url: str = MCP) -> str:
    c = requests.Session()
    h = {"Authorization": f"Bearer {token}", "Accept": "application/json, text/event-stream"}
    r = c.post(url, headers=h, json={"jsonrpc": "2.0", "id": 1, "method": "initialize", "params": {
        "protocolVersion": "2025-06-18", "capabilities": {}, "clientInfo": {"name": "test-stack", "version": "1"}}})
    r.raise_for_status()
    if r.headers.get("mcp-session-id"):
        h["mcp-session-id"] = r.headers["mcp-session-id"]
    r = c.post(url, headers=h, json={"jsonrpc": "2.0", "id": 2, "method": "tools/call",
                                      "params": {"name": tool, "arguments": {}}})
    m = re.search(r"data: (.*)", r.text)
    body = json.loads(m.group(1)) if m else r.json()
    return body["result"]["content"][0]["text"]


def mcp_oauth_flow(login: str, user: str, pwd: str) -> str:
    """An MCP client like LibreChat: discovery, registration, login, consent, token, whoami. Returns whoami."""
    return mcp_call(mcp_token(login, user, pwd), "whoami")


def mcp_token(login: str, user: str, pwd: str, url: str = MCP) -> str:
    """The OAuth part of mcp_oauth_flow: returns an access token for the MCP server at url (the 401 request
    and the resource_metadata come from that URL)."""
    c = requests.Session()
    r = c.post(url, json={"jsonrpc": "2.0", "id": 1, "method": "initialize", "params": {}},
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
    return tok.json()["access_token"]


def itop_keycloak_login(user: str, pwd: str) -> str:
    """Example check 3: Keycloak login into iTop. Returns the name iTop greets."""
    b = browser()
    r = follow(b, b.get(f"{ITOP}/", allow_redirects=False))
    where, r = browse_to_consent(b, r, "keycloak", user, pwd, stop_on_home=True)
    assert where == "home", f"expected iTop's home page, got {where}"
    hi = re.search(r"Hi ([^!]+)!", page_text(r.text, 5000))
    assert hi, "not logged in"
    return hi.group(1)


class _LoginLimited(Exception):
    """LibreChat refused a login request with auth_rate_limited; wait is the seconds until its window ends."""

    def __init__(self, wait: int):
        super().__init__(f"auth_rate_limited, window ends in {wait} s")
        self.wait = wait


class LibreChat:
    """A LibreChat user in a browser."""

    def __init__(self, user: str, pwd: str):
        self.b = browser()
        self.user, self.pwd = user, pwd
        self.h: dict = {}
        self.pkce = None
        self.login_budget = None  # LibreChat's X-RateLimit-Remaining after the last login start
        self.waited = 0           # seconds waited for LibreChat's login limit
        self._reset = None        # X-RateLimit-Reset of the last login start
        self._kc_done = False     # this login got past Keycloak's password form

    def login(self) -> dict:
        """Sign in with Keycloak. LibreChat's login limiter counts every request under /oauth/ per IP (start
        and callback, two per login) against LOGIN_MAX per LOGIN_WINDOW minutes, a fixed window from the
        first request; the test stack raises LOGIN_MAX (TEST_LIBRECHAT_LOGIN_MAX, see README). When LibreChat
        still answers auth_rate_limited, this waits for the window to end and tries once more; refused again,
        the check reports SKIP with the reason (checklib.Skip), never FAIL."""
        cfg = self.b.get(f"{CHAT}/api/config").json()
        assert cfg.get("openidLoginEnabled"), "no Sign in with Keycloak in LibreChat"
        self._kc_done = False
        try:
            return self._login_once(retry=False)
        except _LoginLimited as e:
            self._wait(e.wait, "LibreChat answered auth_rate_limited")
        try:
            return self._login_once(retry=True)
        except _LoginLimited:
            raise Skip(f"LibreChat's login limit: auth_rate_limited again after waiting {self.waited} s for its "
                       "window (raise TEST_LIBRECHAT_LOGIN_MAX, or restart librechat to reset it)") from None

    def _login_once(self, retry: bool) -> dict:
        r = self._start_login()
        q = parse_qs(urlparse(r.headers.get("Location", "")).query)
        self.pkce = q.get("code_challenge_method", [None])[0] or self.pkce
        r = follow(self.b, r)
        self._raise_if_limited(r)
        form = BeautifulSoup(r.text, "lxml").find("form", id="kc-form-login")
        if form is None and r.url.startswith(CHAT) and not (retry and self._kc_done):
            raise AssertionError(f"Keycloak logged in again without asking for a password: {r.url}")
        if form is not None:
            r = _keycloak_login(self.b, r, self.user, self.pwd)
            # The password was accepted; a retry after a refused callback finds Keycloak's session.
            self._kc_done = True
            self._raise_if_limited(r)
        elif not r.url.startswith(CHAT):
            raise AssertionError(f"no Keycloak login form: {r.status_code} {r.url}")
        if "error=" in getattr(r, "url", ""):
            raise AssertionError(f"LibreChat login failed: {r.url}")
        tok = self.b.post(f"{CHAT}/api/auth/refresh")
        assert tok.status_code == 200 and tok.headers.get("content-type", "").startswith("application/json"), \
            f"no LibreChat session: {tok.status_code} {tok.text[:150]}"
        self.h = {"Authorization": "Bearer " + tok.json()["token"]}
        return tok.json()["user"]

    def _start_login(self):
        """The first request of the login. If it used up the budget, the callback would be refused with
        auth_rate_limited: wait for the window to end and start again, instead of failing."""
        r = self.b.get(f"{CHAT}/oauth/openid", allow_redirects=False)
        left, self._reset = r.headers.get("X-RateLimit-Remaining"), r.headers.get("X-RateLimit-Reset")
        self.login_budget = left
        if left is not None and int(left) < 1 and self._reset:
            self._wait(self._until_reset(), "LibreChat login limit reached")
            r = self.b.get(f"{CHAT}/oauth/openid", allow_redirects=False)
            self._reset = r.headers.get("X-RateLimit-Reset")
            self.login_budget = r.headers.get("X-RateLimit-Remaining")
        return r

    def _until_reset(self) -> int:
        """Seconds until LibreChat's login window ends: from X-RateLimit-Reset (epoch seconds) of the last
        login start, else a whole window (LIBRECHAT_LOGIN_WINDOW minutes, LibreChat's default 5)."""
        if self._reset:
            return max(0, int(float(self._reset) - time.time())) + 2
        return int(os.environ.get("LIBRECHAT_LOGIN_WINDOW", "5")) * 60 + 2

    def _wait(self, seconds: int, why: str) -> None:
        print(f"   {why}, waiting {seconds} s for its window", flush=True)
        time.sleep(seconds)
        self.waited += seconds

    def _raise_if_limited(self, r) -> None:
        """LibreChat refuses a request under /oauth/ over the limit with 429 or a redirect to
        /login?error=auth_rate_limited."""
        if isinstance(r, str):
            limited = "auth_rate_limited" in r
        else:
            limited = r.status_code == 429 or "auth_rate_limited" in r.url + r.text[:5000]
        if limited:
            raise _LoginLimited(self._until_reset())

    def config(self) -> dict:
        return self.b.get(f"{CHAT}/api/config", headers=self.h).json()

    def logout(self) -> dict:
        """The Log out menu item: LibreChat ends its session and sends the browser to Keycloak's end-session
        endpoint (OPENID_USE_END_SESSION_ENDPOINT), which ends the Keycloak session and redirects to
        OPENID_POST_LOGOUT_REDIRECT_URI. Returns the end-session URL, whether Keycloak asked "Do you want
        to log out?" and where the browser landed."""
        r = self.b.post(f"{CHAT}/api/auth/logout", headers=self.h)
        assert r.status_code == 200, f"LibreChat logout {r.status_code} {r.text[:200]}"
        redirect = r.json().get("redirect")
        assert redirect, f"LibreChat did not send the browser to Keycloak (OPENID_USE_END_SESSION_ENDPOINT?): {r.json()}"
        self.h = {}
        r = follow(self.b, self.b.get(redirect, allow_redirects=False))
        confirm = BeautifulSoup(r.text, "lxml").find("input", attrs={"name": "confirmLogout"})
        if confirm is not None:  # no id_token_hint: Keycloak asks "Do you want to log out?"
            form = confirm.find_parent("form")
            d = form_data(form)
            d["confirmLogout"] = "Logout"
            r = follow(self.b, self.b.post(urljoin(r.url, form.get("action") or r.url), data=d, allow_redirects=False))
        # Front-channel logout: Keycloak shows a page that loads each client's logout URL in an iframe (for
        # iTop: pages/logoff.php, with iTop's cookie), then continues to the post-logout redirect URI.
        soup = BeautifulSoup(r.text, "lxml")
        frames = [urljoin(r.url, f["src"]) for f in soup.find_all("iframe") if f.get("src")]
        for src in frames:
            follow(self.b, self.b.get(src, allow_redirects=False))
        cont = soup.find("a", id="continue")
        if frames and cont is not None and cont.get("href"):
            r = follow(self.b, self.b.get(urljoin(r.url, cont["href"]), allow_redirects=False))
        assert "Invalid redirect uri" not in r.text,             "Keycloak: Invalid redirect uri (post logout redirect URI missing on the librechat client)"
        return {"end_session": redirect.split("?")[0], "confirmed": confirm is not None, "landed": r.url,
                "frontchannel": [urlparse(f).netloc + urlparse(f).path for f in frames]}

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
            # The browser opens LibreChat's callback; LibreChat exchanges the code there. Its redirect to the
            # page under /oauth/ that says "connected" is not followed: LibreChat's login limiter counts every
            # request under /oauth/, and the logins of the checks need that budget.
            done = self.b.get(cb, allow_redirects=False)
            assert done.status_code < 400 and "error" not in done.headers.get("Location", ""),                 f"LibreChat's MCP callback: {done.status_code} {done.headers.get('Location')}"
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
    """The shared LiteLLM key (LITELLM_KEY from llm.env or LLM_ENV_FILE)."""
    return bool(os.environ.get("LITELLM_KEY"))
