import re

from conftest import ISSUER, RESOURCE_URL, VALID_TOKEN


def _resource_metadata_url(response) -> str:
    m = re.search(r'resource_metadata="([^"]+)"', response.headers["www-authenticate"])
    assert m, response.headers["www-authenticate"]
    return m.group(1)


def test_no_token_returns_401_with_www_authenticate(client, itop):
    r = client.post("initialize")

    assert r.status_code == 401
    assert r.headers["www-authenticate"].startswith("Bearer")
    assert "resource_metadata=" in r.headers["www-authenticate"]
    assert itop.requests == []


def test_token_rejected_by_itop_returns_401(client, itop):
    r = client.call_tool("whoami", token="not-a-valid-token")

    assert r.status_code == 401
    assert "www-authenticate" in r.headers
    assert [req.name for req in itop.requests] == ["list_operations"]
    assert itop.requests[0].auth_token == "not-a-valid-token"


def test_valid_token_is_forwarded_unchanged_as_auth_token_header(client, itop):
    r = client.call_tool("whoami")

    assert r.status_code == 200
    result = r.json()["result"]
    assert result["isError"] is False
    assert "Max Muster" in result["content"][0]["text"]

    assert {req.name for req in itop.requests} == {"list_operations", "core/get"}
    for req in itop.requests:
        assert req.auth_token == VALID_TOKEN
        assert VALID_TOKEN not in req.query_params.values()
        assert VALID_TOKEN not in req.form.values()


def test_protected_resource_metadata_shows_resource_and_issuer(client, itop):
    unauthorized = client.post("initialize")
    metadata_url = _resource_metadata_url(unauthorized)
    # The advertised URL is the public one; fetch the same path from the test server.
    path = re.sub(r"^https?://[^/]+", "", metadata_url)

    r = client.http.get(client.base_url + path)

    assert r.status_code == 200
    doc = r.json()
    assert doc["resource"] == RESOURCE_URL
    assert [s.rstrip("/") for s in doc["authorization_servers"]] == [ISSUER]


def test_valid_token_is_accepted_without_a_resource_check(client, itop):
    # The server switches the MCP SDK's RFC 8707 resource check off explicitly: iTop does not tell
    # which resource a token was issued for, so the verifier reports none. If an SDK update turned
    # the check on (the 3.0 default), every valid iTop token would be refused here with 401.
    from itop_mcp_poc.server import mcp

    r = client.call_tool("whoami")

    assert r.status_code == 200
    assert mcp.settings.auth.validate_token_resource is False
