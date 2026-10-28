"""The old saved-notes feature stays gone: no /v1 or docs surface, no memory scopes, no MCP tools, no static agent tool.

The owner-confirmed preferences memory (Task 6) lives only at /memory and /api/memory, and only with the switch on."""

from test_api_v1 import api  # noqa: F401 (shared fake-phone server fixture)
from test_memory_api import on

from openmob.agent.tools import TOOLS, system_prompt


def test_saved_notes_routes_and_scopes_are_removed(api):
    for path in ("/memory", "/api/memory", "/v1/memory", "/docs/memory"):  # the switch is off by default
        assert api.alice.console.get(path).status_code == 404
    on(api)  # the switch really on: the switch and a store
    assert api.alice.console.get("/api/memory").status_code == 200  # the real routes answer now
    for path in ("/v1/memory", "/docs/memory"):  # and these two stay absent even with it on
        assert api.alice.console.get(path).status_code == 404
    api.manager.cfg.memory, api.manager.memory = False, None
    for scope in ("memory:read", "memory:write"):
        response = api.alice.console.post("/api/developer/keys", json={"password": "password123", "scopes": [scope]})
        assert response.status_code == 400
    for path in ("/", "/developer"):
        page = api.alice.console.get(path)
        assert page.status_code == 200
        assert "What I've learned" not in page.text
        if path == "/developer":  # the dashboard itself carries the switch-gated Save / Not now calls
            assert "/api/memory" not in page.text
        assert "loadPendingNotes" not in page.text


def test_agent_cannot_offer_the_removed_remember_tool():
    assert "remember" not in {tool["name"] for tool in TOOLS}
    assert "call remember" not in system_prompt("android")


def test_mcp_has_no_memory_tools(api):
    from test_mcp import mcp

    on(api)  # even with the switch really on (switch and store)
    names = {t.name for t in mcp(api, api.alice, lambda c: c.list_tools()).tools}
    assert names and not [n for n in names if "memor" in n or "remember" in n or "recall" in n]
