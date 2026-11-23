"""Every tool call writes one JSON line to the audit log, and no log ever contains the token."""
from __future__ import annotations

import logging

import pytest

from conftest import VALID_TOKEN


def _ok(response) -> str:
    assert response.status_code == 200, response.text
    result = response.json()["result"]
    assert result["isError"] is False, result
    return result["content"][0]["text"]


@pytest.mark.parametrize("tool, arguments, logged_args", [
    ("whoami", {}, {}),
    ("search_tickets", {"text": "printer", "status": "new", "ticket_class": "Incident"},
     {"text": "printer", "status": "new", "class": "Incident"}),
    ("get_ticket", {"ref": "R-000123"}, {"ref": "R-000123"}),
    ("oql_query", {"oql": "SELECT Server", "fields": "name"}, {"oql": "SELECT Server", "fields": "name"}),
])
def test_each_tool_call_appends_one_json_line(client, itop, audit, tool, arguments, logged_args):
    _ok(client.call_tool(tool, arguments))

    [entry] = audit.entries()
    assert entry["user"] == "Max Muster"
    assert entry["tool"] == tool
    assert entry["args"] == logged_args
    assert entry["ok"] is True
    assert entry["token"] and entry["token"] != VALID_TOKEN


def test_failed_itop_call_is_logged_with_ok_false(client, itop, audit):
    itop.core_get_error = (100, "Error: invalid OQL")
    try:
        _ok(client.call_tool("oql_query", {"oql": "SELECT Nope"}))
    finally:
        itop.core_get_error = None

    [entry] = audit.entries()
    assert entry["tool"] == "oql_query"
    assert entry["ok"] is False


@pytest.mark.parametrize("tool, arguments", [
    ("oql_query", {"oql": "DELETE FROM Ticket"}),
    ("oql_query", {"oql": "SELECT Person", "fields": "name;x"}),
    ("get_ticket", {"ref": "nope"}),
    ("search_tickets", {"ticket_class": "Person"}),
    ("search_tickets", {"status": "NEW"}),
])
def test_refused_call_is_logged_with_ok_false_without_reaching_itop(client, itop, audit, tool, arguments):
    _ok(client.call_tool(tool, arguments))

    [entry] = audit.entries()
    assert entry["tool"] == tool
    assert entry["ok"] is False
    assert itop.core_gets() == []


def test_token_never_appears_in_audit_file_or_application_log(client, itop, audit, caplog, capfd):
    caplog.set_level(logging.DEBUG)

    # Normal calls, a token smuggled into tool arguments, a refused call and a rejected token.
    _ok(client.call_tool("whoami"))
    _ok(client.call_tool("search_tickets", {"text": VALID_TOKEN}))
    _ok(client.call_tool("oql_query", {"oql": f"SELECT Person WHERE name = '{VALID_TOKEN}'"}))
    _ok(client.call_tool("get_ticket", {"ref": VALID_TOKEN}))
    rejected = "rejected-token-abcdefabcdefabcdefabcdefabcdef"
    assert client.call_tool("whoami", token=rejected).status_code == 401
    itop.http_status = 500
    try:
        assert client.call_tool("whoami").status_code == 401
    finally:
        itop.http_status = None

    raw = audit.raw()
    assert len(audit.entries()) == 4
    assert VALID_TOKEN not in raw
    assert rejected not in raw

    app_log = "\n".join(r.getMessage() for r in caplog.records)
    out, err = capfd.readouterr()
    for text in (app_log, out, err):
        assert VALID_TOKEN not in text
        assert rejected not in text
    assert caplog.records, "expected some application log output to inspect"
