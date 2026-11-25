"""Seam tests for ticket dolibarr-parity 07: accept only OAuth tokens for own resource.

Through the seam (real HTTP, fake iTop extended with mcp/token_info):
- hand-made token (oauth=false) gets 401 + challenge, no tool call reaches iTop
- foreign-resource token gets 401 + challenge, no tool call reaches iTop
- valid OAuth token for own resource works
- extension missing (code 11) gives a clear error
"""
import re

from conftest import ISSUER, RESOURCE_URL, VALID_TOKEN


def _resource_metadata_url(response) -> str:
    m = re.search(r'resource_metadata="([^"]+)"', response.headers["www-authenticate"])
    assert m, response.headers["www-authenticate"]
    return m.group(1)


def test_hand_made_token_is_refused(client, itop):
    """A hand-made personal token (oauth=false) is refused with 401 + challenge."""
    itop.token_info = {
        "class": "PersonalToken",
        "id": 2,
        "oauth": False,
        "resource": None,
        "scopes": ["REST/JSON"],
        "expires_at": None,
    }
    r = client.call_tool("whoami")

    assert r.status_code == 401
    assert "www-authenticate" in r.headers
    # Only the token check reached iTop, no tool call
    assert [req.name for req in itop.requests] == ["mcp/token_info"]


def test_foreign_resource_token_is_refused(client, itop):
    """An OAuth token for another resource is refused with 401 + challenge."""
    itop.token_info = {
        "class": "PersonalToken",
        "id": 3,
        "oauth": True,
        "resource": {"key": "other", "url": "https://other.example.test/mcp"},
        "scopes": ["REST/JSON"],
        "expires_at": None,
    }
    r = client.call_tool("whoami")

    assert r.status_code == 401
    assert "www-authenticate" in r.headers
    assert [req.name for req in itop.requests] == ["mcp/token_info"]


def test_valid_oauth_token_for_own_resource_works(client, itop):
    """A valid OAuth token for MCP_RESOURCE_URL is accepted."""
    # itop fixture already sets up VALID_TOKEN as OAuth for RESOURCE_URL
    r = client.call_tool("whoami")

    assert r.status_code == 200
    result = r.json()["result"]
    assert result["isError"] is False
    assert "Max Muster" in result["content"][0]["text"]
    assert {req.name for req in itop.requests} == {"mcp/token_info", "core/get"}


def test_token_info_unknown_operation_is_refused(client, itop):
    """If the extension is not installed (unknown verb), the token is refused."""
    itop.token_info_unknown = True
    r = client.call_tool("whoami")

    assert r.status_code == 401
    assert "www-authenticate" in r.headers
    assert [req.name for req in itop.requests] == ["mcp/token_info"]


def test_no_token_info_in_response_is_refused(client, itop):
    """If token_info returns null (not a token login), the token is refused."""
    itop.token_info = None
    r = client.call_tool("whoami")

    assert r.status_code == 401
    assert "www-authenticate" in r.headers


def test_initialize_with_hand_made_token_is_refused(client, itop):
    """Even initialize is refused for a hand-made token."""
    itop.token_info = {
        "class": "PersonalToken",
        "id": 4,
        "oauth": False,
        "resource": None,
        "scopes": ["REST/JSON"],
        "expires_at": None,
    }
    r = client.post("initialize", token=VALID_TOKEN)

    assert r.status_code == 401
    assert "www-authenticate" in r.headers


def test_tools_list_with_foreign_resource_token_is_refused(client, itop):
    """tools/list is refused for a foreign-resource token."""
    itop.token_info = {
        "class": "PersonalToken",
        "id": 5,
        "oauth": True,
        "resource": {"key": "other", "url": "https://other.example.test/mcp"},
        "scopes": ["REST/JSON"],
        "expires_at": None,
    }
    r = client.post("tools/list", token=VALID_TOKEN)

    assert r.status_code == 401
    assert "www-authenticate" in r.headers


def test_valid_token_initialize_works(client, itop):
    """initialize works with a valid OAuth token."""
    r = client.post("initialize", token=VALID_TOKEN)

    assert r.status_code == 200
