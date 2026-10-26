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


def test_corrections_survive_memory_clear_via_cosmos(monkeypatch) -> None:
    """The reviewer queue reads the Cosmos repository, not only app.state."""
    monkeypatch.setenv("MSIMULIZI_REVIEWER_KEY", "reviewer-secret")
    app = create_app()
    client = TestClient(app)
    headers = {"x-reviewer-key": "reviewer-secret"}

    created = client.post(
        "/v1/corrections",
        json={
            "profile_key": "match-1.sw.main",
            "moment_id": "moment-1",
            "proposed_body": "Marekebisho",
        },
    )
    assert created.status_code == 200
    correction_id = created.json()["id"]

    # Simulate a process restart: only the durable repository remains.
    app.state.corrections_store.clear()

    queue = client.get("/v1/corrections/queue", headers=headers)
    assert queue.status_code == 200
    assert any(item["id"] == correction_id for item in queue.json()["items"])


def test_session_uses_generator_canonical_match_id() -> None:
    """Session, event, card, and Cosmos IDs must use the same slug format."""
    app = create_app()
    client = TestClient(app)

    response = client.post(
        "/v1/sessions",
        json={
            "storyline": "comeback_from_two_down",
            "seed": 42,
            "speed": 1000,
            "language": "sw",
            "mode": "casual",
        },
    )

    assert response.status_code == 200
    assert response.json()["match_id"] == "comeback-from-two-down-42"


def test_match_state_route_reads_latest_cosmos_snapshot() -> None:
    app = create_app()
    client = TestClient(app)
    asyncio.run(
        app.state.cosmos_repos.match_state_snapshots._container.upsert(
            {
                "id": "match-1:7",
                "match_id": "match-1",
                "sequence_number": 7,
                "minute": 42,
                "second": 5,
                "score_home": 2,
                "score_away": 1,
            }
        )
    )

    response = client.get("/v1/matches/match-1/state")

    assert response.status_code == 200
    assert response.json()["state"]["snapshot"]["minute"] == 42


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
