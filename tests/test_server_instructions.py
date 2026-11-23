"""The server tells the model what the iTop tools are for (ticket setup-docs 12)."""
import re

from conftest import VALID_TOKEN

INIT_PARAMS = {
    "protocolVersion": "2025-06-18",
    "capabilities": {},
    "clientInfo": {"name": "test", "version": "1"},
}


def _instructions(client) -> str:
    r = client.post("initialize", INIT_PARAMS, token=VALID_TOKEN)
    assert r.status_code == 200
    return r.json()["result"].get("instructions") or ""


def _tool_names(client) -> set[str]:
    r = client.post("tools/list", token=VALID_TOKEN)
    assert r.status_code == 200
    return {t["name"] for t in r.json()["result"]["tools"]}


def test_initialize_carries_instructions_on_purpose_and_own_rights(client, itop):
    text = _instructions(client)

    assert "iTop" in text
    assert "ticket" in text.lower()
    # The "own iTop rights" rule
    assert "logged-in user's own iTop account and rights" in text
    assert "only read" in text


def test_instructions_name_only_tools_that_exist(client, itop):
    text = _instructions(client)
    tools = _tool_names(client)

    # Tool names are snake_case identifiers; every one the text mentions must be a real tool.
    mentioned = set(re.findall(r"\b[a-z]+(?:_[a-z0-9]+)+\b|\bwhoami\b", text))
    assert mentioned, text
    assert mentioned <= tools, mentioned - tools
