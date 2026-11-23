"""Requests through the customer's reverse proxy carry the public host name in the Host header.

The host (and port) of MCP_RESOURCE_URL must be accepted; the DNS-rebinding protection stays on
for every other host. Loopback keeps working for the container healthcheck.
"""
from __future__ import annotations

import httpx
import pytest

from conftest import VALID_TOKEN
from fake_itop import free_port
from test_config import start_server  # noqa: F401  (fixture)


def _call_whoami(base_url: str, host: str) -> httpx.Response:
    body = {"jsonrpc": "2.0", "id": 1, "method": "tools/call", "params": {"name": "whoami", "arguments": {}}}
    headers = {"Accept": "application/json, text/event-stream", "Authorization": f"Bearer {VALID_TOKEN}",
               "Host": host}
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
    assert not itop.core_gets()


@pytest.mark.parametrize("loopback", ["localhost", "127.0.0.1"])
def test_loopback_host_keeps_working(mcp_server, itop, loopback):
    port = mcp_server.rsplit(":", 1)[1]

    r = _call_whoami(mcp_server, f"{loopback}:{port}")

    assert r.status_code == 200, r.text


# --- MCP_RESOURCE_URL with an explicit port (separate server process) ------------------------

def test_resource_url_with_explicit_port(start_server, itop):  # noqa: F811
    server = start_server(ITOP_BASE_URL=itop.base_url, MCP_RESOURCE_URL="https://mcp.customer.test:8443/mcp",
                          MCP_HOST="127.0.0.1")
    port = server.base_url.rsplit(":", 1)[1]

    assert _call_whoami(server.base_url, "mcp.customer.test:8443").status_code == 200
    assert _call_whoami(server.base_url, f"localhost:{port}").status_code == 200
    assert _call_whoami(server.base_url, "mcp.customer.test").status_code == 421
    assert _call_whoami(server.base_url, "mcp.customer.test:9999").status_code == 421


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
