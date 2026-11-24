"""Requests through the customer's reverse proxy carry the public host name in the Host header.

The host (and port) of MCP_RESOURCE_URL must be accepted; the DNS-rebinding protection stays on
for every other host. Loopback keeps working for the container healthcheck. The host and origin
check runs before the token check, on every route, so a refused request never reaches iTop.
Equivalent spellings of a host (letter case, trailing dot, IPv6 literal written differently) are the
same host, on the configured and on the incoming side. An IPv4 address must be a dotted quad: other
spellings (127.1, 0x7f.0.0.1, 0177.0.0.1, 2130706433) are refused on both sides with a message that says
why.
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


def _challenge(base_url: str, host: str) -> httpx.Response:
    body = {"jsonrpc": "2.0", "id": 1, "method": "initialize", "params": {}}
    headers = {"Accept": "application/json, text/event-stream", "Host": host}
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


# --- the advertised URL never names the bind address -----------------------------------------

# The server configured exactly as in the container (MCP_HOST=0.0.0.0), but its app served on loopback
# only, so the test never opens a port on all interfaces of the machine it runs on.
_SERVE_WILDCARD_CONFIG_ON_LOOPBACK = """
import uvicorn
from itop_mcp_server import server
assert server.MCP_HOST == "0.0.0.0", server.MCP_HOST
uvicorn.run(server.mcp.streamable_http_app(), host="127.0.0.1", port=server.MCP_PORT, log_level="warning")
"""


def test_public_url_wins_over_a_wildcard_bind_address(start_server, itop):  # noqa: F811
    # Inside the container the server binds 0.0.0.0; that address must never show up in what it advertises.
    server = start_server(["-c", _SERVE_WILDCARD_CONFIG_ON_LOOPBACK], ITOP_BASE_URL=itop.base_url,
                          MCP_RESOURCE_URL="https://mcp.customer.test/mcp", MCP_HOST="0.0.0.0")

    r = _challenge(server.base_url, "mcp.customer.test")

    assert r.status_code == 401
    assert _resource_metadata_url(r) == "https://mcp.customer.test/.well-known/oauth-protected-resource/mcp"
    doc = server.metadata()
    assert doc["resource"] == "https://mcp.customer.test/mcp"
    assert "0.0.0.0" not in r.headers["www-authenticate"] + str(doc)


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


@pytest.mark.parametrize("loopback", ["localhost", "127.0.0.1", "[::1]", "[0:0:0:0:0:0:0:1]", "localhost."])
def test_loopback_host_keeps_working(mcp_server, itop, loopback):
    port = mcp_server.rsplit(":", 1)[1]

    r = _call_whoami(mcp_server, f"{loopback}:{port}")

    assert r.status_code == 200, r.text


# --- equivalent spellings of the public host: trailing dot of a fully qualified name -----------

@pytest.mark.parametrize("host", ["mcp.example.test.", "mcp.example.test.:443", "MCP.Example.Test.:443"])
def test_public_host_with_trailing_dot_is_accepted(mcp_server, itop, host):
    r = _call_whoami(mcp_server, host)

    assert r.status_code == 200, r.text
    assert "Max Muster" in r.json()["result"]["content"][0]["text"]


@pytest.mark.parametrize("origin", ["https://mcp.example.test.", "HTTPS://MCP.Example.Test."])
def test_public_origin_with_trailing_dot_is_accepted(mcp_server, itop, origin):
    r = _call_whoami(mcp_server, "mcp.example.test.", origin)

    assert r.status_code == 200, r.text


@pytest.mark.parametrize("host", ["evil.test.", "mcp.example.test..", "mcp.example.test.evil.test.",
                                  "mcp.example.test.:8443", ".", "[mcp.example.test]", "[2001:db8::5"])
def test_unrelated_or_malformed_host_with_dots_or_brackets_is_refused_with_421(mcp_server, itop, host):
    r = _call_whoami(mcp_server, host)

    assert r.status_code == 421
    assert itop.requests == []


@pytest.mark.parametrize("origin", ["https://evil.test.", "http://mcp.example.test.", "https://mcp.example.test.."])
def test_foreign_origin_with_trailing_dot_is_refused_with_403(mcp_server, itop, origin):
    r = _call_whoami(mcp_server, "mcp.example.test", origin)

    assert r.status_code == 403
    assert itop.requests == []


# --- IPv4 addresses: only the dotted quad, other spellings refused with a clear message ------

DOTTED_QUAD_MESSAGE = "not written as a dotted quad"

# Each of these means 127.0.0.1 to the URL standard and to inet_aton, except the last two, which are
# no valid IPv4 address at all.
ALTERNATIVE_LOOPBACK = ["127.1", "127.0.1", "0x7f.0.0.1", "0x7F000001", "0177.0.0.1", "127.0.0.01",
                        "2130706433", "127.0.0.1.1", "256.0.0.1"]


@pytest.mark.parametrize("host", ALTERNATIVE_LOOPBACK)
def test_loopback_in_alternative_ipv4_spelling_is_refused_with_421_and_says_why(mcp_server, itop, host):
    port = mcp_server.rsplit(":", 1)[1]

    for value in (f"{host}:{port}", host, f"{host}.:{port}"):
        r = _call_whoami(mcp_server, value)
        assert r.status_code == 421, value
        assert DOTTED_QUAD_MESSAGE in r.text, value
    assert itop.requests == []


@pytest.mark.parametrize("host", ["127.1", "0x7f.0.0.1", "2130706433"])
def test_origin_in_alternative_ipv4_spelling_is_refused_with_403_and_says_why(mcp_server, itop, host):
    port = mcp_server.rsplit(":", 1)[1]

    r = _call_whoami(mcp_server, f"127.0.0.1:{port}", f"http://{host}:{port}")

    assert r.status_code == 403
    assert DOTTED_QUAD_MESSAGE in r.text
    assert itop.requests == []


@pytest.mark.parametrize("host", ["evil.test", "192.0.2.10", "127.0.0.1.example.test", "0x7f.example.test"])
def test_unrelated_host_gets_the_plain_421(mcp_server, itop, host):
    r = _call_whoami(mcp_server, host)

    assert r.status_code == 421
    assert DOTTED_QUAD_MESSAGE not in r.text


def test_dotted_quad_loopback_with_trailing_dot_keeps_working(mcp_server, itop):
    port = mcp_server.rsplit(":", 1)[1]

    assert _call_whoami(mcp_server, f"127.0.0.1.:{port}", f"http://127.0.0.1:{port}").status_code == 200


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


def test_resource_url_with_ipv6_host(start_server, itop):  # noqa: F811
    server = start_server(ITOP_BASE_URL=itop.base_url, MCP_RESOURCE_URL="https://[2001:db8::5]/mcp",
                          MCP_HOST="127.0.0.1")

    assert _call_whoami(server.base_url, "[2001:db8::5]").status_code == 200
    assert _call_whoami(server.base_url, "[2001:db8::5]:443").status_code == 200
    assert _call_whoami(server.base_url, "[2001:db8::6]").status_code == 421


@pytest.mark.parametrize("resource_url", ["https://[2001:db8::5]/mcp", "https://[2001:DB8:0::5]/mcp",
                                          "https://[2001:0db8:0000:0000:0000:0000:0000:0005]:443/mcp"],
                         ids=["compressed", "zero-group-capitals", "full-default-port"])
def test_ipv6_host_is_accepted_in_any_spelling(start_server, itop, resource_url):  # noqa: F811
    server = start_server(ITOP_BASE_URL=itop.base_url, MCP_RESOURCE_URL=resource_url, MCP_HOST="127.0.0.1")

    for host in ("[2001:db8::5]", "[2001:db8:0::5]", "[2001:DB8:0:0:0:0:0:5]:443", "[2001:0db8::0005]"):
        r = _call_whoami(server.base_url, host)
        assert r.status_code == 200, (host, r.text)
        assert "Max Muster" in r.json()["result"]["content"][0]["text"]
    assert _call_whoami(server.base_url, "[2001:db8::5]", "https://[2001:db8:0::5]").status_code == 200
    for host in ("[2001:db8::6]", "[2001:db8:0::5]:8443", "2001:db8::5", "[2001:db8::5]x", "[2001:db8::5]."):
        assert _call_whoami(server.base_url, host).status_code == 421, host
    assert _call_whoami(server.base_url, "[2001:db8::5]", "https://[2001:db8::6]").status_code == 403


def test_resource_url_with_trailing_dot_accepts_the_name_with_and_without_it(start_server, itop):  # noqa: F811
    server = start_server(ITOP_BASE_URL=itop.base_url, MCP_RESOURCE_URL="https://mcp.customer.test./mcp",
                          MCP_HOST="127.0.0.1")

    for host in ("mcp.customer.test", "mcp.customer.test.", "mcp.customer.test:443", "MCP.customer.TEST.:443"):
        assert _call_whoami(server.base_url, host).status_code == 200, host
    assert _call_whoami(server.base_url, "mcp.customer.test", "https://mcp.customer.test").status_code == 200
    assert _call_whoami(server.base_url, "mcp.customer.test", "https://mcp.customer.test.").status_code == 200
    assert _call_whoami(server.base_url, "evil.test.").status_code == 421
    assert _call_whoami(server.base_url, "mcp.customer.test..").status_code == 421


def test_resource_url_with_ipv4_host(start_server, itop):  # noqa: F811
    # 192.0.2.10 is also 192.0.522, 0xc0.0.2.10, 0300.0.2.10 and 3221225994 to the URL standard.
    server = start_server(ITOP_BASE_URL=itop.base_url, MCP_RESOURCE_URL="https://192.0.2.10/mcp",
                          MCP_HOST="127.0.0.1")

    for host in ("192.0.2.10", "192.0.2.10:443", "192.0.2.10.", "192.0.2.10.:443"):
        r = _call_whoami(server.base_url, host)
        assert r.status_code == 200, (host, r.text)
        assert "Max Muster" in r.json()["result"]["content"][0]["text"]
    assert _call_whoami(server.base_url, "192.0.2.10", "https://192.0.2.10").status_code == 200
    for host in ("192.0.522", "0xc0.0.2.10", "0300.0.2.10", "192.0.2.010", "3221225994", "3221225994:443"):
        r = _call_whoami(server.base_url, host)
        assert r.status_code == 421, host
        assert DOTTED_QUAD_MESSAGE in r.text, host
    for host in ("192.0.2.11", "192.0.2.10:8443"):
        r = _call_whoami(server.base_url, host)
        assert r.status_code == 421, host
        assert DOTTED_QUAD_MESSAGE not in r.text, host
    r = _call_whoami(server.base_url, "192.0.2.10", "https://0xc0.0.2.10")
    assert r.status_code == 403
    assert DOTTED_QUAD_MESSAGE in r.text
    assert _call_whoami(server.base_url, "192.0.2.10", "https://192.0.2.11").status_code == 403
    assert (_resource_metadata_url(_challenge(server.base_url, "192.0.2.10"))
            == "https://192.0.2.10/.well-known/oauth-protected-resource/mcp")


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


@pytest.mark.parametrize("value", ["https://127.1/mcp", "https://0x7f.0.0.1/mcp", "https://0177.0.0.1:8443/mcp",
                                   "https://2130706433/mcp", "http://192.0.2.010/mcp", "https://256.0.0.1/mcp",
                                   "https://1.2.3.4.5/mcp", "https://192.0.522./mcp"])
def test_resource_url_with_alternative_ipv4_spelling_stops_startup(value):
    from test_config import _run_until_exit

    result = _run_until_exit(ITOP_BASE_URL="https://itop.customer.test", MCP_RESOURCE_URL=value,
                             MCP_HOST="127.0.0.1", MCP_PORT=str(free_port()))

    assert result.returncode != 0
    output = result.stdout + result.stderr
    assert "MCP_RESOURCE_URL" in output
    assert "dotted quad" in output
    assert "Traceback" not in output
