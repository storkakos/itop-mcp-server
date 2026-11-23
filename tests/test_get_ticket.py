"""get_ticket reads a ticket from its own class, so it only asks for attributes that class has.

The class Ticket has no public_log (only UserRequest and Incident do); iTop refuses unknown
attributes in output_fields, so asking Ticket for public_log failed for every ticket.
"""
import json

import pytest

from fake_itop import CLASS_FIELDS


def _ticket_gets(itop):
    """The tool's own requests, without the audit log's lookup of the person."""
    return [g for g in itop.core_gets() if g.operation.get("class") != "Person"]


def _text(response) -> str:
    assert response.status_code == 200, response.text
    return response.json()["result"]["content"][0]["text"]


@pytest.mark.parametrize("ticket_class, has_public_log", [
    ("UserRequest", True),
    ("Incident", True),
    ("Change", False),
])
def test_get_ticket_reads_the_ticket_from_its_own_class(client, itop, audit, ticket_class, has_public_log):
    itop.ticket_class = ticket_class

    text = _text(client.call_tool("get_ticket", {"ref": "R-000002"}))

    [item] = json.loads(text)["items"]
    assert item["class"] == ticket_class
    assert ("public_log" in item) is has_public_log
    assert ("status" in item) is has_public_log
    assert item["description"] == "<description>"
    gets = _ticket_gets(itop)
    second = [f"SELECT {ticket_class} WHERE ref = 'R-000002'"] if has_public_log else []
    assert [g.oql for g in gets] == ["SELECT Ticket WHERE ref = 'R-000002'"] + second
    for g in gets:  # every field list fits the class it was sent to, as iTop requires
        assert set(g.operation["output_fields"].split(",")) <= CLASS_FIELDS[g.operation["class"]]
    [entry] = audit.entries()
    assert entry["ok"] is True, entry


def test_get_ticket_without_a_match_asks_itop_once(client, itop):
    itop.ticket_found = False

    text = _text(client.call_tool("get_ticket", {"ref": "R-000999"}))

    assert text == "Keine Treffer (oder keine Berechtigung)."
    assert [g.oql for g in _ticket_gets(itop)] == ["SELECT Ticket WHERE ref = 'R-000999'"]


@pytest.mark.parametrize("ticket_class", ["UserRequest WHERE 1=1", "Person", "userrequest", ""])
def test_get_ticket_queries_no_class_name_taken_from_the_answer(client, itop, ticket_class):
    """Only a fixed list of class names is ever queried a second time, never one from iTop's answer."""
    itop.ticket_class = ticket_class

    _text(client.call_tool("get_ticket", {"ref": "R-000002"}))

    assert [g.oql for g in _ticket_gets(itop)] == ["SELECT Ticket WHERE ref = 'R-000002'"]
