import asyncio

from fastapi.testclient import TestClient

from api.main import create_app
from api.websocket import WebSocketManager


class FakeWebSocket:
    def __init__(self, *, session_id: str | None = None, profile_key: str | None = None, match_id: str | None = None) -> None:
        self.query_params = {}
        if session_id is not None:
            self.query_params["session_id"] = session_id
        if profile_key is not None:
            self.query_params["profile_key"] = profile_key
        if match_id is not None:
            self.query_params["match_id"] = match_id
        self.sent: list[str] = []
        self.closed = False

    async def accept(self) -> None:
        return None

    async def send_json(self, payload: dict) -> None:
        self.sent.append(str(payload))

    async def send_text(self, payload: str) -> None:
        self.sent.append(payload)

    async def close(self) -> None:
        self.closed = True


def test_websocket_manager_filters_by_profile_key_and_match() -> None:
    async def _run() -> None:
        manager = WebSocketManager()
        ws_a = FakeWebSocket(session_id="a", profile_key="match-1.en.main", match_id="match-1")
        ws_b = FakeWebSocket(session_id="b", profile_key="match-1.fr.main", match_id="match-1")
        await manager.connect(ws_a, session_id="a", profile_key="match-1.en.main", match_id="match-1")
        await manager.connect(ws_b, session_id="b", profile_key="match-1.fr.main", match_id="match-1")

        await manager.broadcast_card("match-1", {"id": "card-1"}, profile_key="match-1.en.main")

        assert any('"id": "card-1"' in item for item in ws_a.sent)
        assert all('"id": "card-1"' not in item for item in ws_b.sent)

    asyncio.run(_run())


def test_reviewer_key_required_on_review_endpoints(monkeypatch) -> None:
    monkeypatch.setenv("MSIMULIZI_REVIEWER_KEY", "reviewer-secret")
    app = create_app()
    client = TestClient(app)

    unauth = client.get("/v1/corrections/queue")
    assert unauth.status_code == 401

    pending = client.get("/v1/corrections/queue", headers={"x-reviewer-key": "reviewer-secret"})
    assert pending.status_code == 200

    audit_blocked = client.get("/v1/audit/match-1/log")
    assert audit_blocked.status_code == 401

    audit_allowed = client.get("/v1/audit/match-1/log", headers={"x-reviewer-key": "reviewer-secret"})
    assert audit_allowed.status_code == 200


def test_reviewer_can_approve_and_reject_corrections(monkeypatch) -> None:
    monkeypatch.setenv("MSIMULIZI_REVIEWER_KEY", "reviewer-secret")
    client = TestClient(create_app())
    headers = {"x-api-key": "reviewer-secret"}

    first = client.post(
        "/v1/corrections",
        json={"profile_key": "match-1.sw.main", "moment_id": "moment-1"},
    )
    second = client.post(
        "/v1/corrections",
        json={"profile_key": "match-1.sw.main", "moment_id": "moment-2"},
    )
    assert first.status_code == 200
    assert second.status_code == 200

    approved = client.post(f"/v1/corrections/{first.json()['id']}/approve", headers=headers)
    rejected = client.post(f"/v1/corrections/{second.json()['id']}/reject", headers=headers)

    assert approved.status_code == 200
    assert approved.json()["status"] == "approved"
    assert rejected.status_code == 200
    assert rejected.json()["status"] == "rejected"
