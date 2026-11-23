"""iTop behind an internal CA: the customer mounts the CA bundle and sets SSL_CERT_FILE.

The fake iTop is served over HTTPS with a certificate from a throwaway test CA. The server runs as
a real process; certificate verification must stay on, so without SSL_CERT_FILE the token check fails.
"""
from __future__ import annotations

import pytest

from conftest import VALID_TOKEN
from fake_itop import FakeITop, free_port, serve_in_thread
from test_config import RESOURCE_URL, start_server  # noqa: F401  (fixture)
from throwaway_ca import make_ca

# An empty value counts as unset, so the CA settings of the test machine play no part.
NO_CA = {"SSL_CERT_FILE": "", "SSL_CERT_DIR": ""}


@pytest.fixture(scope="module")
def tls_itop(tmp_path_factory):
    """A fake iTop on https://localhost:<port> with a certificate from a throwaway CA."""
    files = make_ca(tmp_path_factory.mktemp("ca"), ["localhost", "127.0.0.1"])
    itop = FakeITop()
    port = free_port()
    itop.base_url = f"https://localhost:{port}"
    serve_in_thread(itop.app(), port, ssl_certfile=str(files.cert), ssl_keyfile=str(files.key))
    itop.ca_bundle = files.ca
    return itop


@pytest.fixture
def https_itop(tls_itop):
    tls_itop.reset()
    tls_itop.valid_tokens.add(VALID_TOKEN)
    return tls_itop


def test_with_ssl_cert_file_token_check_and_tool_call_succeed(start_server, https_itop):  # noqa: F811
    server = start_server(ITOP_BASE_URL=https_itop.base_url, MCP_RESOURCE_URL=RESOURCE_URL, MCP_HOST="127.0.0.1",
                          **{**NO_CA, "SSL_CERT_FILE": str(https_itop.ca_bundle)})

    r = server.call_tool("whoami", {})

    assert r.status_code == 200, r.text
    result = r.json()["result"]
    assert result["isError"] is False
    assert "Max Muster" in result["content"][0]["text"]
    assert [req.name for req in https_itop.requests] == ["list_operations", "core/get"]
    assert {req.auth_token for req in https_itop.requests} == {VALID_TOKEN}


def test_without_ssl_cert_file_token_check_fails(start_server, https_itop):  # noqa: F811
    server = start_server(ITOP_BASE_URL=https_itop.base_url, MCP_RESOURCE_URL=RESOURCE_URL, MCP_HOST="127.0.0.1",
                          **NO_CA)

    r = server.call_tool("whoami", {})

    assert r.status_code == 401
    assert r.headers["www-authenticate"].startswith("Bearer")
    # The TLS handshake fails, so not even the token check reaches iTop.
    assert https_itop.requests == []
    assert "Token-Pruefung fehlgeschlagen" in server.stop()
