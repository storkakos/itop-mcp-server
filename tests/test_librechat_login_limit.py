"""The LibreChat login-limit path: wait → retry → success, and wait → retry → SKIP.

Fakes the HTTP side (LibreChat's /oauth/openid and /api/auth/refresh, and Keycloak's login form)
so the test runs with pytest without a stack. The production code under test is flows.py:
LibreChat.login() waits when LibreChat answers auth_rate_limited (429 or a redirect carrying the
error), tries once more, and reports Skip when refused a second time.
"""
from __future__ import annotations

import json
import sys
import time
from pathlib import Path

import pytest

# Make the test-stack client package importable.
sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "test-stack" / "client"))

from checklib import Skip  # noqa: E402
from flows import LibreChat  # noqa: E402


class FakeResponse:
    """Minimal stand-in for a requests response object."""

    def __init__(self, status_code=200, url="https://chat.example.com/", text="", headers=None,
                 json_data=None, location=None):
        self.status_code = status_code
        self.url = url
        self.text = text
        self.headers = headers or {}
        self._json_data = json_data
        if location is not None:
            self.headers["Location"] = location

    def json(self):
        if self._json_data is None:
            return json.loads(self.text)
        return self._json_data


class FakeBrowser:
    """Records calls and returns scripted responses."""

    def __init__(self, script):
        self.script = script  # list of (method, url_prefix, response)
        self.calls = []
        self._idx = 0

    def _next(self, method, url):
        self.calls.append((method, url))
        for i, (m, prefix, resp) in enumerate(self.script):
            if m == method and url.startswith(prefix):
                # Consume this script entry for this call pattern.
                return resp() if callable(resp) else resp
        raise AssertionError(f"no script entry for {method} {url}")

    def get(self, url, **kwargs):
        return self._next("GET", url)

    def post(self, url, **kwargs):
        return self._next("POST", url)


def keycloak_form_response():
    return FakeResponse(
        status_code=200,
        url="https://sso.example.com/realms/example/login",
        text="<html><body><form id='kc-form-login' action='/realms/example/login'><input name='username'><input name='password'></form></body></html>",
    )


def keycloak_redirect_response():
    """Keycloak accepted the password; redirect back to LibreChat's callback."""
    return FakeResponse(
        status_code=302,
        url="https://sso.example.com/realms/example/login",
        location="https://chat.example.com/oauth/openid/callback?code=fake-code&state=fake-state",
    )


def limited_response():
    """LibreChat refuses with auth_rate_limited."""
    return FakeResponse(
        status_code=429,
        url="https://chat.example.com/oauth/openid/callback",
        text="auth_rate_limited",
        headers={"X-RateLimit-Remaining": "0", "X-RateLimit-Reset": str(int(time.time()) + 2)},
    )


def refresh_response():
    return FakeResponse(
        status_code=200,
        url="https://chat.example.com/api/auth/refresh",
        json_data={"token": "fake-token", "user": {"email": "anna@example.com", "name": "Anna Agent"}},
        headers={"content-type": "application/json"},
    )


def config_response():
    return FakeResponse(
        status_code=200,
        url="https://chat.example.com/api/config",
        json_data={"openidLoginEnabled": True, "modelSpecs": {"list": [], "prioritize": False}},
        headers={"content-type": "application/json"},
    )


def openid_start_response(remaining="5", reset=None):
    headers = {"X-RateLimit-Remaining": remaining}
    if reset is not None:
        headers["X-RateLimit-Reset"] = str(reset)
    return FakeResponse(
        status_code=302,
        url="https://chat.example.com/oauth/openid",
        location="https://sso.example.com/realms/example/protocol/openid-connect/auth?code_challenge_method=S256",
        headers=headers,
    )


@pytest.fixture(autouse=True)
def fake_browser(monkeypatch):
    """Replace the browser factory with a scripted fake."""
    fake = FakeBrowser([])
    monkeypatch.setattr("flows.browser", lambda: fake)
    monkeypatch.setattr("flows.time", time)
    return fake


def test_one_refusal_then_retry_succeeds(fake_browser):
    """One auth_rate_limited refusal, then the retry succeeds: wait → retry → success."""
    fake_browser.script = [
        ("GET", "https://chat.example.com/api/config", config_response),
        ("GET", "https://chat.example.com/oauth/openid", lambda: openid_start_response("1")),
        ("GET", "https://sso.example.com/realms/example/protocol/openid-connect/auth", keycloak_form_response),
        ("POST", "https://sso.example.com/realms/example/login", limited_response),
        # After wait, retry:
        ("GET", "https://chat.example.com/oauth/openid", lambda: openid_start_response("1")),
        ("GET", "https://sso.example.com/realms/example/protocol/openid-connect/auth", keycloak_form_response),
        ("POST", "https://sso.example.com/realms/example/login", keycloak_redirect_response),
        ("POST", "https://chat.example.com/api/auth/refresh", refresh_response),
    ]

    lc = LibreChat("anna", "Test-Anna-Pw1!")
    user = lc.login()

    assert user["email"] == "anna@example.com"
    # Should have waited for the limit window.
    assert lc.waited > 0


def test_two_refusals_raise_skip(fake_browser):
    """Two consecutive refusals: wait → retry → refused again → Skip with reason."""
    fake_browser.script = [
        ("GET", "https://chat.example.com/api/config", config_response),
        ("GET", "https://chat.example.com/oauth/openid", lambda: openid_start_response("1")),
        ("GET", "https://sso.example.com/realms/example/protocol/openid-connect/auth", keycloak_form_response),
        ("POST", "https://sso.example.com/realms/example/login", limited_response),
        # After wait, retry:
        ("GET", "https://chat.example.com/oauth/openid", lambda: openid_start_response("1")),
        ("GET", "https://sso.example.com/realms/example/protocol/openid-connect/auth", keycloak_form_response),
        ("POST", "https://sso.example.com/realms/example/login", limited_response),
    ]

    lc = LibreChat("anna", "Test-Anna-Pw1!")
    with pytest.raises(Skip) as exc_info:
        lc.login()

    assert "auth_rate_limited" in str(exc_info.value)
    assert "TEST_LIBRECHAT_LOGIN_MAX" in str(exc_info.value)
    # Should have waited at least once.
    assert lc.waited > 0


def test_no_refusal_succeeds_without_wait(fake_browser):
    """Normal login with no rate limiting: no wait, no retry."""
    fake_browser.script = [
        ("GET", "https://chat.example.com/api/config", config_response),
        ("GET", "https://chat.example.com/oauth/openid", lambda: openid_start_response("5")),
        ("GET", "https://sso.example.com/realms/example/protocol/openid-connect/auth", keycloak_form_response),
        ("POST", "https://sso.example.com/realms/example/login", keycloak_redirect_response),
        ("POST", "https://chat.example.com/api/auth/refresh", refresh_response),
    ]

    lc = LibreChat("anna", "Test-Anna-Pw1!")
    user = lc.login()

    assert user["email"] == "anna@example.com"
    assert lc.waited == 0
