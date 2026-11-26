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


def test_refused_hand_made_token_is_audited_without_the_secret(client, itop, audit):
    itop.token_info = {"class": "PersonalToken", "id": 2, "oauth": False, "resource": None,
                       "scopes": ["REST/JSON"], "expires_at": None}

    assert client.call_tool("whoami").status_code == 401

    [entry] = audit.entries()
    assert entry["tool"] is None and entry["ok"] is False
    assert entry["user"] == "testuser"
    assert entry["info"] == "refused: not an OAuth token"
    assert entry["token"] and VALID_TOKEN not in audit.raw()


def test_refused_foreign_resource_token_is_audited(client, itop, audit):
    itop.token_info = {"class": "PersonalToken", "id": 3, "oauth": True,
                       "resource": {"key": "other", "url": "https://other.example.test/mcp"},
                       "scopes": ["REST/JSON"], "expires_at": None}

    assert client.call_tool("whoami").status_code == 401

    [entry] = audit.entries()
    assert entry["info"] == "refused: OAuth token for another resource"
    assert VALID_TOKEN not in audit.raw()


def test_missing_extension_is_audited_and_logged_clearly(client, itop, audit, caplog):
    itop.token_info_unknown = True

    with caplog.at_level("ERROR", logger="itop-mcp-server"):
        assert client.call_tool("whoami").status_code == 401

    [entry] = audit.entries()
    assert entry["info"] == "refused: iTop extension mcp-token-info missing"
    assert any("mcp-token-info" in r.getMessage() for r in caplog.records)


def test_resource_with_trailing_slash_and_upper_case_host_is_own_resource(client, itop):
    itop.token_info["resource"] = {"key": "mcp", "url": RESOURCE_URL.replace("mcp.example.test", "MCP.example.test") + "/"}

    assert client.call_tool("whoami").status_code == 200


def test_resource_with_other_path_is_refused(client, itop):
    itop.token_info["resource"] = {"key": "mcp", "url": RESOURCE_URL + "/other"}

    assert client.call_tool("whoami").status_code == 401
    assert [req.name for req in itop.requests] == ["mcp/token_info"]


def test_expired_oauth_token_is_refused(client, itop):
    itop.token_info["expires_at"] = 1_000_000_000  # 2001

    assert client.call_tool("whoami").status_code == 401


def test_unknown_token_is_refused_without_audit_line(client, itop, audit):
    assert client.call_tool("whoami", token="not-a-known-token-0123456789").status_code == 401
    assert audit.entries() == []
