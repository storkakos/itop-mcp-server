"""Every tool call lands in the audit log exactly once with a correct ok and info, also when the call
is cancelled or iTop fails.

The rule for ok/info is in the README (section "Audit log"). Cancellation and an unreachable iTop
cannot be produced through the HTTP seam (a client that hangs up does not cancel a JSON-response
call; the token check needs the same iTop), so those tests call the tool in-process with a token in
the request context, like the SDK's auth middleware does after the token check.
"""
from __future__ import annotations

import importlib

import anyio
import pytest
from mcp.server.auth.middleware.auth_context import auth_context_var
from mcp.server.auth.middleware.bearer_auth import AuthenticatedUser
from mcp.server.auth.provider import AccessToken
from mcp.server.fastmcp.exceptions import ToolError

from conftest import VALID_TOKEN
from fake_itop import free_port


def _result(response) -> dict:
    assert response.status_code == 200, response.text
    return response.json()["result"]


def _ok(response) -> str:
    result = _result(response)
    assert result["isError"] is False, result
    return result["content"][0]["text"]


@pytest.fixture
def server(mcp_server):
    return importlib.import_module("itop_mcp_server.server")


def _call_in_process(server, tool: str, arguments: dict, cancel_after: float | None = None) -> bool:
    """Run one tool call in-process; returns True if it was cancelled after cancel_after seconds."""
    async def run() -> bool:
        user = AuthenticatedUser(AccessToken(token=VALID_TOKEN, client_id="test", scopes=["REST/JSON"]))
        reset = auth_context_var.set(user)
        try:
            with anyio.move_on_after(cancel_after) as scope:
                await server.mcp.call_tool(tool, arguments)
            return scope.cancelled_caught
        finally:
            auth_context_var.reset(reset)
    return anyio.run(run)


@pytest.mark.parametrize("tool, arguments", [
    ("list_operations", {}),
    ("smart_query_v2", {"query": "list all servers", "force_class": "Server"}),
    ("oql_query", {"oql": "SELECT Server"}),
    ("whoami", {}),
])
def test_cancelled_call_writes_exactly_one_line(server, itop, audit, tool, arguments):
    itop.delay = 2.0  # iTop is still working on the request when the call is cancelled

    assert _call_in_process(server, tool, arguments, cancel_after=0.5) is True

    assert itop.requests, "the call should have reached iTop before it was cancelled"
    [entry] = audit.entries()
    assert entry["tool"] == tool
    assert entry["user"] == "?"
    assert entry["ok"] is False
    assert entry["info"].startswith("abgebrochen")


@pytest.mark.parametrize("tool, arguments", [
    ("search_tickets", {"text": "printer"}),
    ("get_ticket", {"ref": "R-000123"}),
    ("oql_query", {"oql": "SELECT Server"}),
])
def test_native_call_while_itop_is_unreachable_writes_one_line(server, itop, audit, monkeypatch, tool, arguments):
    monkeypatch.setattr(server, "ITOP_BASE_URL", f"http://127.0.0.1:{free_port()}")

    with pytest.raises(ToolError):
        _call_in_process(server, tool, arguments)

    [entry] = audit.entries()
    assert entry["tool"] == tool
    assert entry["user"] == "?"
    assert entry["ok"] is False
    assert entry["info"].startswith("iTop nicht erreichbar")


@pytest.mark.parametrize("tool, arguments", [
    ("search_tickets", {"text": "printer"}),
    ("get_ticket", {"ref": "R-000123"}),
    ("oql_query", {"oql": "SELECT Server"}),
])
@pytest.mark.parametrize("failure, info", [
    ({"http_status": 500}, "iTop HTTP 500"),
    ({"http_status": 503}, "iTop HTTP 503"),
    ({"html_answer": True}, "iTop lieferte kein JSON"),
])
def test_native_call_with_broken_itop_answer_writes_one_line(client, itop, audit, tool, arguments, failure, info):
    itop.errors_from_request = 1  # let the token check pass
    for name, value in failure.items():
        setattr(itop, name, value)

    result = _result(client.call_tool(tool, arguments))

    assert result["isError"] is True
    [entry] = audit.entries()
    assert entry["tool"] == tool
    assert entry["ok"] is False
    assert entry["info"].startswith(info)


@pytest.mark.parametrize("tool, arguments", [
    ("search_tickets", {"text": "printer"}),
    ("get_ticket", {"ref": "R-000123"}),
    ("oql_query", {"oql": "SELECT Server"}),
])
def test_itop_error_message_lands_in_info_for_native_tools(client, itop, audit, tool, arguments):
    itop.core_get_error = (100, "Error: invalid OQL")

    _ok(client.call_tool(tool, arguments))

    [entry] = audit.entries()
    assert entry["user"] == "Max Muster"
    assert entry["ok"] is False
    assert entry["info"] == "Error: invalid OQL"


@pytest.mark.parametrize("tool, arguments", [
    ("list_operations", {}),
    ("smart_query_v2", {"query": "list all servers", "force_class": "Server"}),
])
def test_itop_error_message_lands_in_info_for_upstream_tools(client, itop, audit, tool, arguments):
    itop.errors_from_request = 1
    itop.core_get_error = (100, "Error: invalid OQL")
    itop.list_operations_error = (100, "Error: invalid OQL")

    _ok(client.call_tool(tool, arguments))

    [entry] = audit.entries()
    assert entry["ok"] is False
    assert entry["info"] == "Error: invalid OQL"


def test_successful_call_has_empty_info(client, itop, audit):
    _ok(client.call_tool("oql_query", {"oql": "SELECT Server"}))

    [entry] = audit.entries()
    assert entry["ok"] is True
    assert entry["info"] == ""


def test_call_that_never_reaches_itop_says_so_in_info(client, itop, audit):
    # A comparison on a class without its own handler is answered by smart_query_v2 without iTop.
    _ok(client.call_tool("smart_query_v2", {"query": "rooms vs desks", "force_class": "Location"}))

    assert itop.core_gets() == [r for r in itop.core_gets() if r.operation.get("class") == "Person"]
    [entry] = audit.entries()
    assert entry["user"] == "Max Muster"
    assert entry["ok"] is False
    assert entry["info"].startswith("kein iTop-Aufruf: ")
    assert "Comparison" in entry["info"]


def test_call_with_one_failed_and_one_good_itop_request_is_not_ok(client, itop, audit):
    # A comparison query asks iTop twice; the tool shows the failed half as an error in its text.
    itop.core_get_error = (100, "Error: first half failed")
    itop.errors_from_request = 1   # after the token check ...
    itop.errors_until_request = 2  # ... only the first of the tool's requests fails

    _ok(client.call_tool("smart_query_v2", {"query": "open vs closed", "force_class": "UserRequest"}))

    tool_requests = [r for r in itop.core_gets() if r.operation.get("class") != "Person"]
    assert len(tool_requests) == 2
    [entry] = audit.entries()
    assert entry["ok"] is False
    assert entry["info"] == "Error: first half failed"


def test_whoami_with_failed_person_lookup_is_not_ok(client, itop, audit):
    itop.errors_from_request = 1
    itop.http_status = 500

    assert _ok(client.call_tool("whoami")) == "Angemeldet in iTop als: ?"

    [entry] = audit.entries()
    assert entry["user"] == "?"
    assert entry["ok"] is False
    assert entry["info"] == "iTop HTTP 500"
    assert len(itop.requests) == 2  # the token check and whoami's own lookup, no second lookup
