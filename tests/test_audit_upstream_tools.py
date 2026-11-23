"""The upstream tools smart_query_v2 and list_operations write to the audit log like the own tools."""
from __future__ import annotations

import logging

import pytest

from conftest import VALID_TOKEN

# One harmless call per tool listed by tools/list. If a tool is added, this map must grow,
# so that no tool can reach iTop without an audit line.
CALL_PER_TOOL = {
    "whoami": {},
    "search_tickets": {"text": "printer"},
    "get_ticket": {"ref": "R-000123"},
    "oql_query": {"oql": "SELECT Server"},
    "smart_query_v2": {"query": "list all servers", "force_class": "Server", "limit": 5},
    "list_operations": {},
}


def _result(response) -> str:
    assert response.status_code == 200, response.text
    result = response.json()["result"]
    assert result["isError"] is False, result
    return result["content"][0]["text"]


def test_every_listed_tool_is_covered(client, itop):
    r = client.post("tools/list", token=VALID_TOKEN)
    assert {t["name"] for t in r.json()["result"]["tools"]} == set(CALL_PER_TOOL)


@pytest.mark.parametrize("tool", sorted(CALL_PER_TOOL))
def test_every_tool_call_appends_exactly_one_line(client, itop, audit, tool):
    _result(client.call_tool(tool, CALL_PER_TOOL[tool]))

    [entry] = audit.entries()
    assert entry["tool"] == tool


def test_smart_query_v2_call_is_audited(client, itop, audit):
    _result(client.call_tool("smart_query_v2", {"query": "list all servers", "force_class": "Server", "limit": 5}))

    [entry] = audit.entries()
    assert entry["user"] == "Max Muster"
    assert entry["tool"] == "smart_query_v2"
    assert entry["args"]["query"] == "list all servers"
    assert entry["args"]["force_class"] == "Server"
    assert entry["args"]["limit"] == 5
    assert entry["ok"] is True
    assert entry["token"] and entry["token"] != VALID_TOKEN


def test_list_operations_call_is_audited(client, itop, audit):
    _result(client.call_tool("list_operations"))

    [entry] = audit.entries()
    assert entry["user"] == "Max Muster"
    assert entry["tool"] == "list_operations"
    assert entry["args"] == {}
    assert entry["ok"] is True
    assert entry["token"] and entry["token"] != VALID_TOKEN


@pytest.mark.parametrize("tool, arguments, failure", [
    ("smart_query_v2", {"query": "list all servers", "force_class": "Server"}, {"core_get_error": (100, "Error: invalid OQL")}),
    ("smart_query_v2", {"query": "list all servers", "force_class": "Server"}, {"http_status": 500}),
    ("list_operations", {}, {"list_operations_error": (1, "Error: something broke")}),
    ("list_operations", {}, {"http_status": 500}),
])
def test_call_failing_at_itop_is_logged_with_ok_false(client, itop, audit, tool, arguments, failure):
    # Request 0 is the token check; let it pass and fail the tool's own call.
    itop.errors_from_request = 1
    for name, value in failure.items():
        setattr(itop, name, value)

    _result(client.call_tool(tool, arguments))

    [entry] = audit.entries()
    assert entry["tool"] == tool
    assert entry["ok"] is False


def test_token_never_appears_in_audit_or_log_for_upstream_tools(client, itop, audit, caplog, capfd):
    caplog.set_level(logging.DEBUG)

    _result(client.call_tool("list_operations"))
    _result(client.call_tool("smart_query_v2", {"query": f"servers named {VALID_TOKEN}", "force_class": "Server"}))
    itop.http_status = 500
    # Each call starts with a token check; let it pass and fail the tool's own iTop calls.
    itop.errors_from_request = len(itop.requests) + 1
    _result(client.call_tool("list_operations"))
    itop.errors_from_request = len(itop.requests) + 1
    _result(client.call_tool("smart_query_v2", {"query": "list all servers", "force_class": "Server"}))

    raw = audit.raw()
    assert len(audit.entries()) == 4
    assert VALID_TOKEN not in raw
    app_log = "\n".join(r.getMessage() for r in caplog.records)
    out, err = capfd.readouterr()
    for text in (app_log, out, err):
        assert VALID_TOKEN not in text


def test_upstream_tool_interface_is_unchanged(client, itop):
    r = client.post("tools/list", token=VALID_TOKEN)
    tools = {t["name"]: t for t in r.json()["result"]["tools"]}

    sq = tools["smart_query_v2"]["inputSchema"]
    assert set(sq["properties"]) == {"query", "force_class", "limit"}
    assert sq["required"] == ["query"]
    assert sq["properties"]["limit"]["default"] == 100
    assert tools["smart_query_v2"]["description"].strip()
    assert tools["list_operations"]["inputSchema"].get("properties", {}) == {}
    assert tools["list_operations"]["description"] == "List all available operations in the iTop REST API."

    text = _result(client.call_tool("list_operations"))
    assert text.startswith("Available iTop REST API operations:")
