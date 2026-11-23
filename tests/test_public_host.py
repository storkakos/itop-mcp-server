"""Requests through the customer's reverse proxy carry the public host name in the Host header.

The host (and port) of MCP_RESOURCE_URL must be accepted; the DNS-rebinding protection stays on
for every other host. Loopback keeps working for the container healthcheck. The host and origin
check runs before the token check, on every route, so a refused request never reaches iTop.
"""
from __future__ import annotations

import re
import uuid

import httpx
import pytest

from conftest import RESOURCE_URL, VALID_TOKEN
from fake_itop import free_port
from test_config import start_server  # noqa: F401  (fixture)

PUBLIC_METADATA_URL = "https://mcp.example.test/.well-known/oauth-protected-resource/mcp"


def _call_whoami(base_url: str, host: str, origin: str | None = None) -> httpx.Response:
    body = {"jsonrpc": "2.0", "id": 1, "method": "tools/call", "params": {"name": "whoami", "arguments": {}}}
    headers = {"Accept": "application/json, text/event-stream", "Authorization": f"Bearer {VALID_TOKEN}",
               "Host": host}
    if origin is not None:
        headers["Origin"] = origin
    return httpx.post(f"{base_url}/mcp", json=body, headers=headers, timeout=30)


def _resource_metadata_url(response: httpx.Response) -> str:
    m = re.search(r'resource_metadata="([^"]+)"', response.headers["www-authenticate"])
    assert m, response.headers["www-authenticate"]
    return m.group(1)


def _fresh_token(itop, valid: bool) -> str:
    """A token the server has never seen before, so a token check would have to ask iTop."""
    token = f"fresh-{uuid.uuid4().hex}"
    if valid:
        itop.valid_tokens.add(token)
    return token


def _post_mcp(base_url: str, host: str, token: str | None, origin: str | None = None) -> httpx.Response:
    body = {"jsonrpc": "2.0", "id": 1, "method": "tools/call", "params": {"name": "whoami", "arguments": {}}}
    headers = {"Accept": "application/json, text/event-stream", "Host": host}
    if token is not None:
        headers["Authorization"] = f"Bearer {token}"
    if origin is not None:
        headers["Origin"] = origin
    return httpx.post(f"{base_url}/mcp", json=body, headers=headers, timeout=30)


# --- MCP_RESOURCE_URL without a port (in-process seam: https://mcp.example.test/mcp) --------

@pytest.mark.parametrize("host", ["mcp.example.test", "mcp.example.test:443"])
def test_public_host_of_resource_url_is_accepted(mcp_server, itop, host):
    r = _call_whoami(mcp_server, host)

    assert r.status_code == 200, r.text
    assert "Max Muster" in r.json()["result"]["content"][0]["text"]


@pytest.mark.parametrize("host", ["evil.test", "mcp.example.test.evil.test", "mcp.example.test:8443",
                                  "evil.test:443"])
def test_unrelated_host_is_refused_with_421(mcp_server, itop, host):
    r = _call_whoami(mcp_server, host)

    assert r.status_code == 421
    assert itop.requests == []


@pytest.mark.parametrize("host", ["MCP.Example.TEST", "Mcp.Example.Test:443"])
def test_public_host_in_other_letter_case_is_accepted(mcp_server, itop, host):
    r = _call_whoami(mcp_server, host)

    assert r.status_code == 200, r.text


@pytest.mark.parametrize("host", ["EVIL.test", "MCP.Example.TEST:8443"])
def test_unrelated_host_in_capitals_is_still_refused_with_421(mcp_server, itop, host):
    r = _call_whoami(mcp_server, host)

    assert r.status_code == 421
    assert itop.requests == []


@pytest.mark.parametrize("origin", ["https://mcp.example.test", "HTTPS://MCP.Example.Test"])
def test_public_origin_is_accepted_in_any_letter_case(mcp_server, itop, origin):
    r = _call_whoami(mcp_server, "mcp.example.test", origin)

    assert r.status_code == 200, r.text


@pytest.mark.parametrize("origin", ["https://evil.test", "http://mcp.example.test", "https://mcp.example.test:8443"])
def test_foreign_origin_is_refused_with_403(mcp_server, itop, origin):
    r = _call_whoami(mcp_server, "mcp.example.test", origin)

    assert r.status_code == 403
    assert itop.requests == []


@pytest.mark.parametrize("loopback", ["localhost", "127.0.0.1"])
def test_loopback_host_keeps_working(mcp_server, itop, loopback):
    port = mcp_server.rsplit(":", 1)[1]

    r = _call_whoami(mcp_server, f"{loopback}:{port}")

    assert r.status_code == 200, r.text


# --- the host and origin check comes before the token check ----------------------------------

TOKEN_KINDS = ["valid-token", "invalid-token", "no-token"]


def _token_of_kind(itop, kind: str) -> str | None:
    return None if kind == "no-token" else _fresh_token(itop, valid=kind == "valid-token")


@pytest.mark.parametrize("kind", TOKEN_KINDS)
def test_foreign_host_gets_421_before_any_token_check(mcp_server, itop, kind):
    r = _post_mcp(mcp_server, "evil.test", _token_of_kind(itop, kind))

    assert r.status_code == 421
    assert r.text == "Invalid Host header"
    assert "www-authenticate" not in r.headers
    assert itop.requests == []


@pytest.mark.parametrize("kind", TOKEN_KINDS)
def test_foreign_origin_gets_403_before_any_token_check(mcp_server, itop, kind):
    r = _post_mcp(mcp_server, "mcp.example.test", _token_of_kind(itop, kind), origin="https://evil.test")

    assert r.status_code == 403
    assert r.text == "Invalid Origin header"
    assert "www-authenticate" not in r.headers
    assert itop.requests == []


@pytest.mark.parametrize("kind", TOKEN_KINDS)
def test_metadata_with_foreign_host_gets_421(mcp_server, itop, kind):
    token = _token_of_kind(itop, kind)
    headers = {"Host": "evil.test", **({"Authorization": f"Bearer {token}"} if token else {})}

    r = httpx.get(f"{mcp_server}/.well-known/oauth-protected-resource/mcp", headers=headers, timeout=10)

    assert r.status_code == 421
    assert RESOURCE_URL not in r.text
    assert itop.requests == []


def test_metadata_with_foreign_origin_gets_403(mcp_server, itop):
    r = httpx.get(f"{mcp_server}/.well-known/oauth-protected-resource/mcp",
                  headers={"Host": "mcp.example.test", "Origin": "https://evil.test"}, timeout=10)

    assert r.status_code == 403
    assert itop.requests == []


@pytest.mark.parametrize("host", ["mcp.example.test", "loopback"])
def test_allowed_host_still_gets_the_401_challenge_and_works_with_a_new_token(mcp_server, itop, host):
    if host == "loopback":
        host = f"127.0.0.1:{mcp_server.rsplit(':', 1)[1]}"

    challenge = _post_mcp(mcp_server, host, None)
    rejected = _post_mcp(mcp_server, host, _fresh_token(itop, valid=False))
    accepted = _post_mcp(mcp_server, host, _fresh_token(itop, valid=True))

    assert challenge.status_code == 401
    assert _resource_metadata_url(challenge) == PUBLIC_METADATA_URL
    assert rejected.status_code == 401
    assert accepted.status_code == 200, accepted.text
    assert "Max Muster" in accepted.json()["result"]["content"][0]["text"]


# --- MCP_RESOURCE_URL with an explicit port (separate server process) ------------------------

def test_resource_url_with_explicit_port(start_server, itop):  # noqa: F811
    server = start_server(ITOP_BASE_URL=itop.base_url, MCP_RESOURCE_URL="https://mcp.customer.test:8443/mcp",
                          MCP_HOST="127.0.0.1")
    port = server.base_url.rsplit(":", 1)[1]

    assert _call_whoami(server.base_url, "mcp.customer.test:8443").status_code == 200
    assert _call_whoami(server.base_url, f"localhost:{port}").status_code == 200
    assert _call_whoami(server.base_url, "mcp.customer.test").status_code == 421
    assert _call_whoami(server.base_url, "mcp.customer.test:9999").status_code == 421
    assert _call_whoami(server.base_url, "mcp.customer.test:8443", "https://mcp.customer.test:8443").status_code == 200
    assert _call_whoami(server.base_url, "mcp.customer.test:8443", "https://mcp.customer.test").status_code == 403


@pytest.mark.parametrize(("resource_url", "public_host", "default_port", "origin"), [
    ("https://mcp.customer.test:443/mcp", "mcp.customer.test", 443, "https://mcp.customer.test"),
    ("http://mcp.customer.test:80/mcp", "mcp.customer.test", 80, "http://mcp.customer.test"),
], ids=["https-443", "http-80"])
def test_resource_url_with_default_port_behaves_like_url_without_port(start_server, itop, resource_url,  # noqa: F811
                                                                      public_host, default_port, origin):
    server = start_server(ITOP_BASE_URL=itop.base_url, MCP_RESOURCE_URL=resource_url, MCP_HOST="127.0.0.1")

    for host in (public_host, f"{public_host}:{default_port}"):
        r = _call_whoami(server.base_url, host)
        assert r.status_code == 200, (host, r.text)
        assert "Max Muster" in r.json()["result"]["content"][0]["text"]
    assert _call_whoami(server.base_url, public_host, origin).status_code == 200
    assert _call_whoami(server.base_url, public_host, f"{origin}:{default_port}").status_code == 403
    assert _call_whoami(server.base_url, f"{public_host}:8443").status_code == 421


# --- MCP_RESOURCE_URL must name a host -------------------------------------------------------

@pytest.mark.parametrize("value", ["mcp.customer.test/mcp", "ftp://mcp.customer.test/mcp", "https:///mcp"])
def test_resource_url_without_http_host_stops_startup(value):
    from test_config import _run_until_exit

    result = _run_until_exit(ITOP_BASE_URL="https://itop.customer.test", MCP_RESOURCE_URL=value,
                             MCP_HOST="127.0.0.1", MCP_PORT=str(free_port()))

    assert result.returncode != 0
    output = result.stdout + result.stderr
    assert "MCP_RESOURCE_URL" in output
    assert "Traceback" not in output
