"""
Unit tests for mcp/server.py.

Covers:
- get_match_state: live (pub/sub) path, snapshot (Cosmos) path, not found
- list_key_moments: unfiltered, filtered by tag, filtered by priority
- get_player_stats: live path, snapshot fallback, not found
- Missing/invalid API key returns ErrorResult for every tool

Requirements: 11.1 – 11.4
"""

from __future__ import annotations

import asyncio
import pytest

from shared.cosmos import CosmosRepositories, FakeCosmosContainer
from shared.pubsub import PubSub
import mcp_server.server as mcp_module
from mcp_server.server import (
    get_match_state,
    list_key_moments,
    get_player_stats,
    ErrorResult,
    set_dependencies,
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def run(coro):
    return asyncio.run(coro)


def make_repos() -> CosmosRepositories:
    containers = {name: FakeCosmosContainer() for name in CosmosRepositories.CONTAINER_NAMES}
    containers["audit_log"] = FakeCosmosContainer(create_only=True)
    return CosmosRepositories(containers)


VALID_KEY = "test-secret-key"
VALID_AUTH = f"Bearer {VALID_KEY}"


@pytest.fixture(autouse=True)
def wire_dependencies(monkeypatch):
    """Wire fake repos and bus; patch MCP_API_KEY for each test."""
    repos = make_repos()
    bus = PubSub()
    set_dependencies(repos, bus)
    monkeypatch.setattr(mcp_module, "_MCP_API_KEY", VALID_KEY)
    return repos, bus


# ---------------------------------------------------------------------------
# get_match_state
# ---------------------------------------------------------------------------

class TestGetMatchState:
    def test_returns_live_state_from_pubsub(self, wire_dependencies):
        repos, bus = wire_dependencies
        live_state = {
            "match_id": "m1",
            "minute": 42,
            "second": 10,
            "score_home": 1,
            "score_away": 0,
            "team_home": "Nyota FC",
            "team_away": "Jua United",
            "possession_home": 0.62,
            "field_tilt_home": 0.55,
            "field_tilt_away": 0.45,
            "xg_home": 1.2,
            "xg_away": 0.4,
            "momentum_home": 65.0,
            "momentum_away": 35.0,
            "pressure_rate_home": 0.12,
            "pressure_rate_away": 0.08,
            "tempo": 14.5,
        }
        run(bus.publish("match_state:session-42", live_state))

        result = run(get_match_state("m1", session_id="session-42", authorization=VALID_AUTH))

        assert not isinstance(result, ErrorResult)
        assert result.minute == 42
        assert result.score_home == 1
        assert result.source == "live"

    def test_falls_back_to_cosmos_snapshot(self, wire_dependencies):
        repos, bus = wire_dependencies
        snapshot = {
            "id": "m1:5",
            "match_id": "m1",
            "sequence_number": 5,
            "minute": 30,
            "second": 0,
            "score_home": 0,
            "score_away": 1,
            "team_home": "Nyota FC",
            "team_away": "Jua United",
            "possession_home": 0.4,
            "field_tilt_home": 0.3,
            "field_tilt_away": 0.7,
            "xg_home": 0.5,
            "xg_away": 1.8,
            "momentum_home": 40.0,
            "momentum_away": 60.0,
            "pressure_rate_home": 0.05,
            "pressure_rate_away": 0.18,
            "tempo": 11.0,
        }
        run(repos.match_state_snapshots._container.upsert(snapshot))

        result = run(get_match_state("m1", authorization=VALID_AUTH))

        assert not isinstance(result, ErrorResult)
        assert result.score_away == 1
        assert result.source == "snapshot"

    def test_returns_not_found_when_no_state(self, wire_dependencies):
        result = run(get_match_state("unknown-match", authorization=VALID_AUTH))
        assert isinstance(result, ErrorResult)
        assert result.error == "NotFound"

    def test_missing_key_returns_unauthorized(self, wire_dependencies):
        result = run(get_match_state("m1", authorization=None))
        assert isinstance(result, ErrorResult)
        assert result.error == "Unauthorized"

    def test_wrong_key_returns_unauthorized(self, wire_dependencies):
        result = run(get_match_state("m1", authorization="Bearer wrong"))
        assert isinstance(result, ErrorResult)
        assert result.error == "Unauthorized"


# ---------------------------------------------------------------------------
# list_key_moments
# ---------------------------------------------------------------------------

class TestListKeyMoments:
    def _seed_moments(self, repos: CosmosRepositories):
        moments = [
            {
                "id": "m1-km-0001", "moment_id": "m1-km-0001", "match_id": "m1",
                "trigger_event_id": "m1-000010", "trigger_tags": ["goal", "lead_change"],
                "priority_rank": 1, "minute": 35, "second": 22,
                "structured_explanation": {"reason": "Goal scored", "theme": "control_vs_chaos"},
            },
            {
                "id": "m1-km-0002", "moment_id": "m1-km-0002", "match_id": "m1",
                "trigger_event_id": "m1-000050", "trigger_tags": ["momentum_swing"],
                "priority_rank": 3, "minute": 60, "second": 0,
                "structured_explanation": {"reason": "Pressure shift", "theme": "pressure_change"},
            },
            {
                "id": "m1-km-0003", "moment_id": "m1-km-0003", "match_id": "m1",
                "trigger_event_id": "m1-000080", "trigger_tags": ["goal"],
                "priority_rank": 1, "minute": 88, "second": 5,
                "structured_explanation": None,
            },
        ]
        for m in moments:
            run(repos.key_moments._container.upsert(m))

    def test_returns_all_moments_unfiltered(self, wire_dependencies):
        repos, _ = wire_dependencies
        self._seed_moments(repos)
        result = run(list_key_moments("m1", authorization=VALID_AUTH))
        assert not isinstance(result, ErrorResult)
        assert len(result) == 3

    def test_filters_by_trigger_tag(self, wire_dependencies):
        repos, _ = wire_dependencies
        self._seed_moments(repos)
        result = run(list_key_moments("m1", trigger_tags=["goal"], authorization=VALID_AUTH))
        assert not isinstance(result, ErrorResult)
        assert all("goal" in r.trigger_tags for r in result)
        assert len(result) == 2

    def test_filters_by_min_priority(self, wire_dependencies):
        repos, _ = wire_dependencies
        self._seed_moments(repos)
        result = run(list_key_moments("m1", min_priority=1, authorization=VALID_AUTH))
        assert not isinstance(result, ErrorResult)
        assert all(r.priority_rank <= 1 for r in result)
        assert len(result) == 2

    def test_respects_limit(self, wire_dependencies):
        repos, _ = wire_dependencies
        self._seed_moments(repos)
        result = run(list_key_moments("m1", limit=2, authorization=VALID_AUTH))
        assert not isinstance(result, ErrorResult)
        assert len(result) <= 2

    def test_includes_reason_from_explanation(self, wire_dependencies):
        repos, _ = wire_dependencies
        self._seed_moments(repos)
        result = run(list_key_moments("m1", trigger_tags=["goal"], authorization=VALID_AUTH))
        assert not isinstance(result, ErrorResult)
        with_reason = [r for r in result if r.reason is not None]
        assert len(with_reason) >= 1

    def test_missing_key_returns_unauthorized(self, wire_dependencies):
        result = run(list_key_moments("m1", authorization=None))
        assert isinstance(result, ErrorResult)
        assert result.error == "Unauthorized"


# ---------------------------------------------------------------------------
# get_player_stats
# ---------------------------------------------------------------------------

class TestGetPlayerStats:
    def _live_state_with_player(self, player: str) -> dict:
        return {
            "match_id": "m1",
            "minute": 70,
            "second": 0,
            "score_home": 2,
            "score_away": 1,
            "team_home": "Nyota FC",
            "team_away": "Jua United",
            "possession_home": 0.55,
            "field_tilt_home": 0.5,
            "field_tilt_away": 0.5,
            "xg_home": 2.1,
            "xg_away": 0.9,
            "momentum_home": 55.0,
            "momentum_away": 45.0,
            "pressure_rate_home": 0.10,
            "pressure_rate_away": 0.07,
            "tempo": 13.0,
            "player_stats": {
                player: {
                    "player": player,
                    "team": "Nyota FC",
                    "passes_attempted": 40,
                    "passes_completed": 34,
                    "pass_distance_total": 320.0,
                    "shots": 3,
                    "shots_on_target": 2,
                    "xg_total": 0.65,
                    "goals": 1,
                    "tackles_attempted": 2,
                    "tackles_won": 1,
                    "interceptions": 1,
                    "cards": 0,
                }
            },
        }

    def test_returns_live_stats_from_pubsub(self, wire_dependencies):
        repos, bus = wire_dependencies
        state = self._live_state_with_player("Juma Baraka")
        run(bus.publish("match_state:sess-1", state))

        result = run(get_player_stats("m1", "Juma Baraka", session_id="sess-1", authorization=VALID_AUTH))

        assert not isinstance(result, ErrorResult)
        assert result.player == "Juma Baraka"
        assert result.goals == 1
        assert result.pass_accuracy == pytest.approx(34 / 40, abs=0.001)
        assert result.source == "live"

    def test_falls_back_to_cosmos_snapshot(self, wire_dependencies):
        repos, bus = wire_dependencies
        state = self._live_state_with_player("Amara Diallo")
        snapshot = {
            "id": "m1:10",
            "match_id": "m1",
            "sequence_number": 10,
            **state,
        }
        run(repos.match_state_snapshots._container.upsert(snapshot))

        result = run(get_player_stats("m1", "Amara Diallo", authorization=VALID_AUTH))

        assert not isinstance(result, ErrorResult)
        assert result.player == "Amara Diallo"
        assert result.shots == 3
        assert result.source == "snapshot"

    def test_returns_not_found_for_unknown_player(self, wire_dependencies):
        result = run(get_player_stats("m1", "Unknown Player", authorization=VALID_AUTH))
        assert isinstance(result, ErrorResult)
        assert result.error == "NotFound"

    def test_missing_key_returns_unauthorized(self, wire_dependencies):
        result = run(get_player_stats("m1", "Anyone", authorization=None))
        assert isinstance(result, ErrorResult)
        assert result.error == "Unauthorized"
