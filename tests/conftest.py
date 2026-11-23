"""Test seam: the MCP server over real HTTP, with a fake iTop behind it.

Tests act like an MCP client (JSON-RPC POSTs to /mcp with a Bearer token, GETs on the
.well-known metadata). Nothing inside the server is mocked.
"""
from __future__ import annotations

import importlib
import os

import httpx
import pytest

from fake_itop import FakeITop, free_port, serve_in_thread

RESOURCE_URL = "https://mcp.example.test/mcp"
ISSUER = "https://itop.example.test/env-production/altioo-oauth-server"
VALID_TOKEN = "valid-token-0123456789abcdef0123456789abcdef"
# Distinct from the server default (50) and from the tools' default limit (20).
MAX_ROWS = 25


@pytest.fixture(scope="session")
def fake_itop() -> FakeITop:
    itop = FakeITop()
    port = free_port()
    itop.base_url = f"http://127.0.0.1:{port}"
    serve_in_thread(itop.app(), port)
    return itop


@pytest.fixture(scope="session")
def mcp_server(fake_itop, tmp_path_factory) -> str:
    """Start the MCP server once per session; returns its base URL."""
    port = free_port()
    os.environ.update({
        "ITOP_BASE_URL": fake_itop.base_url,
        "ITOP_OAUTH_ISSUER": ISSUER,
        "MCP_RESOURCE_URL": RESOURCE_URL,
        "MCP_HOST": "127.0.0.1",
        "MCP_PORT": str(port),
        "MCP_MAX_ROWS": str(MAX_ROWS),
        "MCP_AUDIT_LOG": str(tmp_path_factory.mktemp("logs") / "audit.log"),
    })
    # Configuration is read at import time, so import only after the environment is set.
    server = importlib.import_module("itop_mcp_poc.server")
    serve_in_thread(server.mcp.streamable_http_app(), port)
    return f"http://127.0.0.1:{port}"


@pytest.fixture
def itop(fake_itop) -> FakeITop:
    """The fake iTop, reset for each test, accepting VALID_TOKEN."""
    fake_itop.reset()
    fake_itop.valid_tokens.add(VALID_TOKEN)
    return fake_itop


class MCPClient:
    def __init__(self, base_url: str):
        self.base_url = base_url
        self.http = httpx.Client(timeout=30)
        self._id = 0

    def post(self, method: str, params: dict | None = None, token: str | None = None) -> httpx.Response:
        self._id += 1
        headers = {"Accept": "application/json, text/event-stream"}
        if token is not None:
            headers["Authorization"] = f"Bearer {token}"
        body = {"jsonrpc": "2.0", "id": self._id, "method": method, "params": params or {}}
        return self.http.post(f"{self.base_url}/mcp", json=body, headers=headers)

    def call_tool(self, name: str, arguments: dict | None = None, token: str = VALID_TOKEN) -> httpx.Response:
        return self.post("tools/call", {"name": name, "arguments": arguments or {}}, token=token)


@pytest.fixture
def client(mcp_server) -> MCPClient:
    c = MCPClient(mcp_server)
    yield c
    c.http.close()
