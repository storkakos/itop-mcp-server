"""TEST ONLY. Check group "proxy": the reverse proxy blocks of README.md. The path-prefix check runs only
in the nginx variant (compose.nginx.yaml) and is skipped otherwise. No LibreChat needed."""
import requests

import flows
from checklib import Group
from common import ISSUER, LOCAL_USER, MCP_PREFIX, metadata_url

group = Group(__name__, "Reverse proxy (README.md)", order=20)
check = group.check


@check("README: MCP server and its metadata under a path prefix (nginx)")
def _():
    if not MCP_PREFIX:
        return "SKIP only in the nginx variant (compose.nginx.yaml)"
    meta = metadata_url(MCP_PREFIX)
    r = requests.post(MCP_PREFIX, json={"jsonrpc": "2.0", "id": 1, "method": "initialize", "params": {}},
                      headers={"Accept": "application/json, text/event-stream"})
    assert r.status_code == 401, r.status_code
    assert f'resource_metadata="{meta}"' in r.headers["www-authenticate"], r.headers["www-authenticate"]
    d = requests.get(meta).json()
    assert d["resource"] == MCP_PREFIX and d["authorization_servers"] == [ISSUER], d
    answer = flows.mcp_call(flows.mcp_token("form", LOCAL_USER[0], LOCAL_USER[1], url=MCP_PREFIX), "whoami", MCP_PREFIX)
    assert f"{LOCAL_USER[2]} {LOCAL_USER[3]}" in answer, answer
    return MCP_PREFIX
