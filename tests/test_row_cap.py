"""Results are capped at MCP_MAX_ROWS in what reaches iTop."""
import pytest

from conftest import MAX_ROWS


def _limits(itop, cls: str) -> list[int]:
    return [r.operation["limit"] for r in itop.core_gets() if r.operation.get("class") == cls]


@pytest.mark.parametrize("requested", [MAX_ROWS + 1, 1000, 10**9])
def test_oql_query_limit_above_max_rows_is_capped(client, itop, requested):
    r = client.call_tool("oql_query", {"oql": "SELECT Server", "limit": requested})

    assert r.status_code == 200, r.text
    assert _limits(itop, "Server") == [MAX_ROWS]


@pytest.mark.parametrize("requested", [MAX_ROWS + 1, 1000])
def test_search_tickets_limit_above_max_rows_is_capped(client, itop, requested):
    r = client.call_tool("search_tickets", {"ticket_class": "Incident", "limit": requested})

    assert r.status_code == 200, r.text
    assert _limits(itop, "Incident") == [MAX_ROWS]


def test_limit_within_max_rows_is_passed_through(client, itop):
    client.call_tool("oql_query", {"oql": "SELECT Server", "limit": MAX_ROWS - 1})

    assert _limits(itop, "Server") == [MAX_ROWS - 1]


@pytest.mark.parametrize("requested", [0, -5])
def test_limit_below_one_is_raised_to_one(client, itop, requested):
    client.call_tool("oql_query", {"oql": "SELECT Server", "limit": requested})

    assert _limits(itop, "Server") == [1]


def test_upstream_smart_query_is_capped_too(client, itop):
    """smart_query_v2 comes from the unchanged upstream module and defaults to limit=100."""
    r = client.call_tool("smart_query_v2", {"query": "how many servers", "force_class": "Server", "limit": 1000})

    assert r.status_code == 200, r.text
    limits = [g.operation["limit"] for g in itop.core_gets()]
    assert limits, "smart_query_v2 sent no core/get"
    assert max(limits) <= MAX_ROWS
