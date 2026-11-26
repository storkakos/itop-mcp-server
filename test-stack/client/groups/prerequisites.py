"""TEST ONLY. Check group "prerequisites": the check list of docs/setup/itop-prerequisites.md.
Needs only the setup's part of the stack (no LibreChat, no Mongo)."""
import re
from pathlib import Path

import requests

import flows
from checklib import Group
from common import CONFIG, ISSUER, ITOP, LOCAL_USER, MCP, MCP_METADATA

group = Group(__name__, "iTop prerequisites (docs/setup/itop-prerequisites.md)", order=10)
check = group.check


@check("prerequisites 1: authorization server metadata at the site root")
def _():
    d = requests.get(f"{ITOP}/.well-known/oauth-authorization-server/env-production/altioo-oauth-server").json()
    assert d["issuer"] == ISSUER, d["issuer"]
    for k in ("authorization_endpoint", "token_endpoint", "registration_endpoint"):
        assert d.get(k), k


@check("prerequisites 2: MCP server answers 401 with resource_metadata")
def _():
    r = requests.post(MCP, json={"jsonrpc": "2.0", "id": 1, "method": "initialize", "params": {}},
                      headers={"Accept": "application/json, text/event-stream"})
    assert r.status_code == 401, r.status_code
    assert f'resource_metadata="{MCP_METADATA}"' in r.headers["www-authenticate"], r.headers["www-authenticate"]


@check("prerequisites 3: protected-resource metadata points at iTop")
def _():
    d = requests.get(MCP_METADATA).json()
    assert d["resource"] == MCP and d["authorization_servers"] == [ISSUER], d


@check("prerequisites 4: resource URL identical in MCP server, metadata and config-itop.php")
def _():
    d = requests.get(MCP_METADATA).json()
    m = re.search(r"'itop-mcp' => array\(.*?'url' => '([^']+)'", Path(CONFIG).read_text(), re.S)
    assert m and m.group(1) == d["resource"] == MCP, (m and m.group(1), d["resource"])


@check("prerequisites 5: MCP client connects (iTop login form, consent, whoami)")
def _():
    answer = flows.mcp_oauth_flow("form", LOCAL_USER[0], LOCAL_USER[1])
    assert f"{LOCAL_USER[2]} {LOCAL_USER[3]}" in answer, answer
    return answer


@check("prerequisites: all four discovery URLs answer with the metadata")
def _():
    urls = [
        f"{ITOP}/.well-known/oauth-authorization-server/env-production/altioo-oauth-server",
        f"{ITOP}/.well-known/openid-configuration/env-production/altioo-oauth-server",
        f"{ITOP}/env-production/altioo-oauth-server/.well-known/oauth-authorization-server",
        f"{ITOP}/env-production/altioo-oauth-server/.well-known/openid-configuration",
    ]
    for u in urls:
        r = requests.get(u)
        assert r.status_code == 200, f"{u}: {r.status_code}"
        d = r.json()
        assert d.get("issuer") == ISSUER, f"{u}: issuer {d.get('issuer')}"


@check("prerequisites: extension directory is private except index.php")
def _():
    for p in ("README.md", "src/", "vendor/autoload.php"):
        code = requests.get(f"{ISSUER}/{p}").status_code
        assert code in (403, 404), f"{p}: {code}"
