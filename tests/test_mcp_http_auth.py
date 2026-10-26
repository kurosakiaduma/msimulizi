"""HTTP-boundary tests for the mounted MCP server.

The MCP tools had unit-level key checks, but the FastAPI mount used to expose a
separate unauthenticated stub. These tests exercise the real mount:

* missing/wrong Bearer token -> 401 before MCP protocol handling
* valid token -> tools can be initialized and called
* the validated HTTP token satisfies the per-tool check, so clients do not
  need to repeat it as a tool argument
"""

from __future__ import annotations

import asyncio

from fastapi.testclient import TestClient

import mcp_server.server as mcp_module
from api.main import create_app


AUTH_HEADERS = {
    "Authorization": "Bearer test-mcp-secret",
    "Accept": "application/json, text/event-stream",
    "Content-Type": "application/json",
}


def _jsonrpc(method: str, params: dict, request_id: int) -> dict:
    return {
        "jsonrpc": "2.0",
        "id": request_id,
        "method": method,
        "params": params,
    }


def test_mcp_mount_rejects_missing_or_wrong_bearer(monkeypatch) -> None:
    monkeypatch.setattr(mcp_module, "_MCP_API_KEY", "test-mcp-secret")
    app = create_app()

    with TestClient(app) as client:
        missing = client.get("/mcp/")
        wrong = client.get("/mcp/", headers={"Authorization": "Bearer wrong"})

    assert missing.status_code == 401
    assert missing.headers.get("www-authenticate", "").lower().startswith("bearer")
    assert wrong.status_code == 401
    assert "Unauthorized" in missing.json()["error"]


def test_mcp_mount_accepts_valid_bearer_and_calls_tools(monkeypatch) -> None:
    monkeypatch.setattr(mcp_module, "_MCP_API_KEY", "test-mcp-secret")
    app = create_app()

    with TestClient(app) as client:
        repos = app.state.cosmos_repos
        asyncio.run(
            repos.key_moments._container.upsert(
                {
                    "id": "m1-km-0001",
                    "moment_id": "m1-km-0001",
                    "match_id": "m1",
                    "trigger_event_id": "m1-000010",
                    "trigger_tags": ["goal"],
                    "priority_rank": 1,
                    "minute": 35,
                    "second": 22,
                    "structured_explanation": {
                        "reason": "Goal scored",
                        "theme": "control_vs_chaos",
                    },
                }
            )
        )

        init = client.post(
            "/mcp/",
            headers=AUTH_HEADERS,
            json=_jsonrpc(
                "initialize",
                {
                    "protocolVersion": "2025-06-18",
                    "capabilities": {},
                    "clientInfo": {"name": "pytest", "version": "0"},
                },
                1,
            ),
        )
        assert init.status_code == 200
        assert "msimulizi-mcp" in init.text

        # No per-tool `authorization` argument: the HTTP middleware supplies it.
        call = client.post(
            "/mcp/",
            headers=AUTH_HEADERS,
            json=_jsonrpc(
                "tools/call",
                {
                    "name": "list_key_moments",
                    "arguments": {"match_id": "m1"},
                },
                2,
            ),
        )

    assert call.status_code == 200
    assert "m1-km-0001" in call.text
    assert "Unauthorized" not in call.text
