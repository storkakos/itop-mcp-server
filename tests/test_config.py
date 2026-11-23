"""Configuration contract: the server is started as a real process with a given environment.

Checked from outside only: exit code and startup output, the protected-resource metadata,
and what reaches the fake iTop.
"""
from __future__ import annotations

import os
import subprocess
import sys
import tempfile
import time

import httpx
import pytest

from conftest import VALID_TOKEN
from fake_itop import free_port

RESOURCE_URL = "https://mcp.customer.test/mcp"
CONFIG_VARS = ("ITOP_BASE_URL", "ITOP_OAUTH_ISSUER", "ITOP_API_VERSION", "MCP_RESOURCE_URL",
               "MCP_HOST", "MCP_PORT", "MCP_MAX_ROWS", "MCP_AUDIT_LOG")


def _env(**config: str) -> dict[str, str]:
    """The current environment without any server setting, plus the given ones."""
    env = {k: v for k, v in os.environ.items() if k not in CONFIG_VARS}
    env.update(config)
    env["PYTHONUNBUFFERED"] = "1"
    return env


def _start(**config: str) -> subprocess.Popen:
    # Output goes to a temp file, not a pipe: nobody reads the pipe while the server runs, and once
    # its buffer is full the server blocks on logging and stops answering.
    output = tempfile.TemporaryFile(mode="w+", encoding="utf-8")
    proc = subprocess.Popen([sys.executable, "-m", "itop_mcp_poc.server"], env=_env(**config),
                            stdout=output, stderr=subprocess.STDOUT, text=True)
    proc.output = output
    return proc


def _output(proc: subprocess.Popen) -> str:
    proc.output.seek(0)
    return proc.output.read()


def _run_until_exit(**config: str) -> subprocess.CompletedProcess:
    return subprocess.run([sys.executable, "-m", "itop_mcp_poc.server"], env=_env(**config),
                          capture_output=True, text=True, timeout=30)


class RunningServer:
    def __init__(self, proc: subprocess.Popen, base_url: str):
        self.proc = proc
        self.base_url = base_url

    def metadata(self) -> dict:
        r = httpx.get(f"{self.base_url}/.well-known/oauth-protected-resource/mcp", timeout=10)
        assert r.status_code == 200
        return r.json()

    def call_tool(self, name: str, arguments: dict) -> httpx.Response:
        body = {"jsonrpc": "2.0", "id": 1, "method": "tools/call", "params": {"name": name, "arguments": arguments}}
        headers = {"Accept": "application/json, text/event-stream", "Authorization": f"Bearer {VALID_TOKEN}"}
        return httpx.post(f"{self.base_url}/mcp", json=body, headers=headers, timeout=30)

    def stop(self) -> str:
        """Stop the server and return everything it printed."""
        self.proc.terminate()
        self.proc.wait(timeout=10)
        out = _output(self.proc)
        self.proc.output.close()
        return out


@pytest.fixture
def start_server(tmp_path):
    started: list[RunningServer] = []

    def start(**config: str) -> RunningServer:
        port = int(config.setdefault("MCP_PORT", str(free_port())))
        config.setdefault("MCP_AUDIT_LOG", str(tmp_path / "audit.log"))
        proc = _start(**config)
        server = RunningServer(proc, f"http://127.0.0.1:{port}")
        started.append(server)
        deadline = time.monotonic() + 20
        while True:
            if proc.poll() is not None:
                pytest.fail(f"server exited early:\n{_output(proc)}")
            try:
                httpx.get(f"{server.base_url}/.well-known/oauth-protected-resource/mcp", timeout=1)
                return server
            except httpx.TransportError:
                if time.monotonic() > deadline:
                    pytest.fail("server did not start")
                time.sleep(0.1)

    yield start
    for server in started:
        if server.proc.poll() is None:
            server.stop()


# --- required variables: fail fast, name the variable --------------------------------------

@pytest.mark.parametrize("missing", ["ITOP_BASE_URL", "MCP_RESOURCE_URL"])
@pytest.mark.parametrize("value", [None, "", "   "], ids=["unset", "empty", "blank"])
def test_missing_required_variable_stops_startup_and_names_it(missing, value):
    config = {"ITOP_BASE_URL": "https://itop.customer.test", "MCP_RESOURCE_URL": RESOURCE_URL,
              "MCP_HOST": "127.0.0.1", "MCP_PORT": str(free_port())}
    if value is None:
        del config[missing]
    else:
        config[missing] = value

    result = _run_until_exit(**config)

    assert result.returncode != 0
    output = result.stdout + result.stderr
    assert missing in output
    assert "Traceback" not in output
    assert "Uvicorn running" not in output


@pytest.mark.parametrize("var", ["MCP_PORT", "MCP_MAX_ROWS"])
def test_non_numeric_value_stops_startup_and_names_it(var):
    config = {"ITOP_BASE_URL": "https://itop.customer.test", "MCP_RESOURCE_URL": RESOURCE_URL,
              "MCP_HOST": "127.0.0.1", "MCP_PORT": str(free_port()), var: "abc"}

    result = _run_until_exit(**config)

    assert result.returncode != 0
    output = result.stdout + result.stderr
    assert var in output
    assert "Traceback" not in output


# --- issuer and resource in the metadata ----------------------------------------------------

def test_issuer_is_derived_from_itop_base_url(start_server):
    server = start_server(ITOP_BASE_URL="https://itop.customer.test/", MCP_RESOURCE_URL=RESOURCE_URL,
                          MCP_HOST="127.0.0.1")

    doc = server.metadata()

    assert doc["resource"] == RESOURCE_URL
    assert [s.rstrip("/") for s in doc["authorization_servers"]] == [
        "https://itop.customer.test/env-production/altioo-oauth-server"]


def test_itop_oauth_issuer_overrides_the_derived_issuer(start_server):
    server = start_server(ITOP_BASE_URL="https://itop.customer.test", MCP_RESOURCE_URL=RESOURCE_URL,
                          ITOP_OAUTH_ISSUER="https://login.customer.test/oauth", MCP_HOST="127.0.0.1")

    doc = server.metadata()

    assert [s.rstrip("/") for s in doc["authorization_servers"]] == ["https://login.customer.test/oauth"]


# --- optional settings and their defaults ---------------------------------------------------

def test_defaults_for_api_version_and_row_cap(start_server, itop):
    server = start_server(ITOP_BASE_URL=itop.base_url, MCP_RESOURCE_URL=RESOURCE_URL, MCP_HOST="127.0.0.1")

    r = server.call_tool("oql_query", {"oql": "SELECT Server", "limit": 999})

    assert r.status_code == 200
    gets = [g for g in itop.core_gets() if g.oql == "SELECT Server"]
    assert len(gets) == 1
    assert gets[0].operation["limit"] == 50
    assert {req.form["version"] for req in itop.requests} == {"1.3"}


def test_api_version_and_row_cap_are_configurable(start_server, itop):
    server = start_server(ITOP_BASE_URL=itop.base_url, MCP_RESOURCE_URL=RESOURCE_URL, MCP_HOST="127.0.0.1",
                          ITOP_API_VERSION="1.4", MCP_MAX_ROWS="7")

    r = server.call_tool("oql_query", {"oql": "SELECT Server", "limit": 999})

    assert r.status_code == 200
    gets = [g for g in itop.core_gets() if g.oql == "SELECT Server"]
    assert gets[0].operation["limit"] == 7
    assert {req.form["version"] for req in itop.requests} == {"1.4"}


def test_audit_log_goes_to_configured_path(start_server, itop, tmp_path):
    audit = tmp_path / "custom" / "audit.jsonl"
    server = start_server(ITOP_BASE_URL=itop.base_url, MCP_RESOURCE_URL=RESOURCE_URL, MCP_HOST="127.0.0.1",
                          MCP_AUDIT_LOG=str(audit))

    assert server.call_tool("whoami", {}).status_code == 200

    assert audit.exists()
    assert '"tool": "whoami"' in audit.read_text(encoding="utf-8")


def test_defaults_for_host_and_audit_log_are_container_friendly():
    port = free_port()
    proc = _start(ITOP_BASE_URL="https://itop.customer.test", MCP_RESOURCE_URL=RESOURCE_URL, MCP_PORT=str(port))
    server = RunningServer(proc, f"http://127.0.0.1:{port}")
    try:
        deadline = time.monotonic() + 20
        while True:
            assert proc.poll() is None, _output(proc)
            try:
                server.metadata()
                break
            except httpx.TransportError:
                assert time.monotonic() < deadline, "server did not start"
                time.sleep(0.1)
    finally:
        output = server.stop()

    # Listens on all interfaces, and the audit log sits in the data folder, not next to the source code.
    assert f"0.0.0.0:{port}" in output
    assert "/data/logs/mcp-itop-audit.log" in output
