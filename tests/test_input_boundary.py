"""Rejected input never reaches iTop, and only read-only tools are exposed."""
import pytest

from conftest import VALID_TOKEN


def _text(response) -> str:
    assert response.status_code == 200, response.text
    return response.json()["result"]["content"][0]["text"]


@pytest.mark.parametrize("oql", [
    "DELETE FROM Ticket",
    "UPDATE Ticket SET title = 'x'",
    "INSERT INTO Ticket (title) VALUES ('x')",
    "",
    "   ",
    "SELECT",
    "SELECT * FROM Ticket",
    "Person WHERE id = 1",
    "-- SELECT Person",
    "SELECT Person; DELETE Person",
    "SELECT Person WHERE name = 'a;b'",
    "SELECT Person;",
])
def test_oql_query_refuses_non_single_select(client, itop, oql):
    text = _text(client.call_tool("oql_query", {"oql": oql}))

    assert text == "Nur einzelne SELECT-Abfragen sind erlaubt."
    assert itop.core_gets() == []


@pytest.mark.parametrize("fields", [
    "",
    "name;email",
    "name' OR 1=1",
    "name,email)",
    "name.email",
    "a" * 401,
])
def test_oql_query_refuses_invalid_field_list(client, itop, fields):
    text = _text(client.call_tool("oql_query", {"oql": "SELECT Person", "fields": fields}))

    assert text == "Ungueltige Feldliste"
    assert itop.core_gets() == []


@pytest.mark.parametrize("ref", [
    "",
    "R000123",
    "r-000123",
    "R-",
    "R-0001234567890",
    "ABCD-1",
    "R-1' OR '1'='1",
    "R-1 OR 1=1",
    "R-000123;",
    "1-000123",
])
def test_get_ticket_refuses_invalid_reference(client, itop, ref):
    text = _text(client.call_tool("get_ticket", {"ref": ref}))

    assert text == "Ungueltige Ticketreferenz"
    assert itop.core_gets() == []


@pytest.mark.parametrize("ticket_class", ["Person", "userrequest", "UserRequest WHERE 1=1", "", "Ticket;"])
def test_search_tickets_refuses_unknown_class(client, itop, ticket_class):
    text = _text(client.call_tool("search_tickets", {"ticket_class": ticket_class}))

    assert text == "Ungueltige Ticketklasse"
    assert itop.core_gets() == []


@pytest.mark.parametrize("status", ["New", "x", "new' OR '1'='1", "new;", "a" * 31, "new status", "n3w"])
def test_search_tickets_refuses_invalid_status(client, itop, status):
    text = _text(client.call_tool("search_tickets", {"status": status}))

    assert text == "Ungueltiger Status"
    assert itop.core_gets() == []


def test_valid_input_does_reach_itop(client, itop):
    """Control case: the refusal tests above would pass vacuously if nothing ever reached iTop."""
    _text(client.call_tool("oql_query", {"oql": "SELECT Person WHERE id = 1", "fields": "name, email"}))
    _text(client.call_tool("get_ticket", {"ref": " R-000123 "}))
    _text(client.call_tool("search_tickets", {"status": "assigned", "ticket_class": "Incident"}))

    oqls = [r.oql for r in itop.core_gets()]
    assert "SELECT Person WHERE id = 1" in oqls
    assert "SELECT Ticket WHERE ref = 'R-000123'" in oqls
    assert "SELECT Incident WHERE status = 'assigned'" in oqls
    [oql_get] = [r for r in itop.core_gets() if r.oql == "SELECT Person WHERE id = 1"]
    assert oql_get.operation["output_fields"] == "name,email"


def test_search_text_quotes_cannot_break_out_of_the_like_clause(client, itop):
    _text(client.call_tool("search_tickets", {"text": "x' OR '1'='1"}))

    [get] = [r for r in itop.core_gets() if r.operation.get("class") == "UserRequest"]
    assert get.oql == "SELECT UserRequest WHERE (title LIKE '%x\\' OR \\'1\\'=\\'1%' OR ref LIKE '%x\\' OR \\'1\\'=\\'1%')"


READ_ONLY_TOOLS = {"whoami", "search_tickets", "get_ticket", "oql_query", "smart_query_v2", "list_operations"}


def test_only_read_only_tools_are_listed(client, itop):
    r = client.post("tools/list", token=VALID_TOKEN)

    assert r.status_code == 200, r.text
    names = {t["name"] for t in r.json()["result"]["tools"]}
    assert names == READ_ONLY_TOOLS
    for name in names:
        assert not any(w in name.lower() for w in ("create", "update", "delete", "stimulus", "write", "set_"))
