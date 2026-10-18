"""
Unit tests for shared/cosmos.py.

Covers:
- Upsert idempotence (MatchStateSnapshotRepository)
- Write buffering after simulated failure
- Create-only audit behaviour (AuditLogRepository)
- OverlayCard TTL for spotlight cards
- NarrationCacheRepository round-trip
- CosmosRepositories factory wiring

All async calls are driven through asyncio.run() so no async test plugin
is required.
"""

from __future__ import annotations

import asyncio
import dataclasses
from datetime import datetime

import pytest

import shared.cosmos as cosmos_mod
from shared.cosmos import (
    AuditLogRepository,
    ConflictError,
    CosmosRepositories,
    FakeCosmosContainer,
    MatchStateSnapshotRepository,
    NarrationCacheRepository,
    OverlayCardRepository,
    WriteBuffer,
    _TTL_SPOTLIGHT_SECONDS,
)
from shared.models import (
    KeyMoment,
    MatchState,
    NarratorResponse,
    OverlayCard,
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def run(coro):
    """Run a coroutine synchronously."""
    return asyncio.run(coro)


def _make_state(sequence_number: int = 1, session_id: str = "s1") -> MatchState:
    return MatchState(
        match_id="match01",
        session_id=session_id,
        sequence_number=sequence_number,
        last_event_id=f"match01-{sequence_number:06d}",
        minute=10,
        second=0,
        score_home=0,
        score_away=0,
        possession_home=0.5,
        field_tilt_home=0.3,
        field_tilt_away=0.2,
        xg_home=0.4,
        xg_away=0.3,
        momentum_home=55.0,
        momentum_away=45.0,
        pressure_rate_home=2.0,
        pressure_rate_away=1.5,
        tempo=12.0,
        player_stats={},
        updated_at=datetime(2026, 10, 1, 12, 0, 0),
    )


def _make_card(card_type: str = "key_moment") -> OverlayCard:
    return OverlayCard(
        card_id=f"card-{card_type}",
        match_id="match01",
        profile_key="match01.en.casual.neutral",
        match_clock={"period": 1, "minute": 25, "second": 0},
        match_seconds=1500.0,
        display_duration_ms=6000,
        card_type=card_type,
        priority=1,
        player_ref=None,
        team_ref="Team A",
        text={"en": {"headline": "Goal!", "body": "Team A scores."}},
        gloss_en=None,
        structured_explanation=None,
    )


def _make_narrator_response() -> NarratorResponse:
    return NarratorResponse(
        profile_key="match01.en.casual.neutral",
        moment_id="match01-km-0001",
        headline="Goal!",
        body="Team A scored in the 25th minute.",
        generated_at=datetime(2026, 10, 1, 12, 0, 0),
    )


# ---------------------------------------------------------------------------
# MatchStateSnapshotRepository — upsert idempotence
# ---------------------------------------------------------------------------

class TestMatchStateSnapshotRepository:
    def test_upsert_and_get_round_trip(self):
        repo = MatchStateSnapshotRepository(FakeCosmosContainer())
        state = _make_state(sequence_number=5)
        run(repo.upsert_snapshot(state))
        doc = run(repo.get_snapshot("match01", 5))
        assert doc is not None
        assert doc["sequence_number"] == 5
        assert doc["match_id"] == "match01"

    def test_upsert_idempotent(self):
        repo = MatchStateSnapshotRepository(FakeCosmosContainer())
        state = _make_state(sequence_number=1)
        run(repo.upsert_snapshot(state))
        state2 = dataclasses.replace(state, minute=20)
        run(repo.upsert_snapshot(state2))
        doc = run(repo.get_snapshot("match01", 1))
        assert doc["minute"] == 20

    def test_different_sequences_stored_independently(self):
        repo = MatchStateSnapshotRepository(FakeCosmosContainer())
        run(repo.upsert_snapshot(_make_state(sequence_number=1)))
        run(repo.upsert_snapshot(_make_state(sequence_number=2)))
        doc1 = run(repo.get_snapshot("match01", 1))
        doc2 = run(repo.get_snapshot("match01", 2))
        assert doc1 is not None
        assert doc2 is not None
        assert doc1["id"] != doc2["id"]

    def test_missing_returns_none(self):
        repo = MatchStateSnapshotRepository(FakeCosmosContainer())
        result = run(repo.get_snapshot("match01", 99))
        assert result is None


# ---------------------------------------------------------------------------
# Write buffer — buffering after simulated failure
# ---------------------------------------------------------------------------

class TestWriteBuffer:
    def _isolated_repo(self):
        """Return (container, repo, buf) with an isolated WriteBuffer."""
        container = FakeCosmosContainer()
        buf = WriteBuffer()
        original = cosmos_mod._buffer
        cosmos_mod._buffer = buf
        return container, MatchStateSnapshotRepository(container), buf, original

    def test_buffer_filled_on_total_failure(self):
        container, repo, buf, original = self._isolated_repo()
        try:
            # Exhaust all retries (3 retries + 1 initial = 4 attempts).
            container.fail_next_n = 4
            run(repo.upsert_snapshot(_make_state(sequence_number=1)))
            # Document not persisted yet.
            assert run(repo.get_snapshot("match01", 1)) is None
            # Landed in the buffer.
            assert buf.pending_count == 1
        finally:
            cosmos_mod._buffer = original

    def test_buffer_flushed_when_container_recovers(self):
        container, repo, buf, original = self._isolated_repo()
        try:
            container.fail_next_n = 4
            run(repo.upsert_snapshot(_make_state(sequence_number=7)))
            assert buf.pending_count == 1

            # Container healthy — flush should persist the document.
            remaining = run(buf.flush())
            assert remaining == 0
            assert run(repo.get_snapshot("match01", 7)) is not None
        finally:
            cosmos_mod._buffer = original

    def test_buffer_item_stays_if_still_failing(self):
        container, repo, buf, original = self._isolated_repo()
        try:
            container.fail_next_n = 4   # exhaust retries → buffered
            run(repo.upsert_snapshot(_make_state(sequence_number=3)))
            assert buf.pending_count == 1

            # Container still unhealthy; item should remain buffered.
            container.fail_next_n = 1
            remaining = run(buf.flush())
            assert remaining == 1
        finally:
            cosmos_mod._buffer = original


# ---------------------------------------------------------------------------
# AuditLogRepository — create-only behaviour
# ---------------------------------------------------------------------------

class TestAuditLogRepository:
    def _repo(self):
        return AuditLogRepository(FakeCosmosContainer(create_only=True))

    def test_create_entry_succeeds(self):
        repo = self._repo()
        entry = {"id": "log-001", "match_id": "match01", "verdict": "pass"}
        run(repo.create_entry(entry))
        docs = run(repo.list_entries("match01"))
        assert any(d["id"] == "log-001" for d in docs)

    def test_duplicate_create_raises(self):
        repo = self._repo()
        entry = {"id": "log-dup", "match_id": "match01"}
        run(repo.create_entry(entry))
        with pytest.raises(Exception):   # ConflictError or OSError from backoff
            run(repo.create_entry(entry))

    def test_upsert_blocked(self):
        repo = self._repo()
        with pytest.raises(PermissionError):
            run(repo._write_with_retry("upsert", {"id": "x", "match_id": "m"}))

    def test_missing_id_raises(self):
        repo = self._repo()
        with pytest.raises(ValueError, match="id"):
            run(repo.create_entry({"match_id": "match01"}))

    def test_missing_match_id_raises(self):
        repo = self._repo()
        with pytest.raises(ValueError, match="match_id"):
            run(repo.create_entry({"id": "log-x"}))


# ---------------------------------------------------------------------------
# OverlayCardRepository — TTL for spotlight cards
# ---------------------------------------------------------------------------

class TestOverlayCardRepository:
    def _repo(self):
        return OverlayCardRepository(FakeCosmosContainer())

    def test_spotlight_card_gets_ttl(self):
        repo = self._repo()
        card = _make_card(card_type="player_spotlight")
        run(repo.upsert_card(card))
        doc = run(repo.get_card(card.card_id, "match01"))
        assert doc is not None
        assert doc["ttl"] == _TTL_SPOTLIGHT_SECONDS

    def test_non_spotlight_card_no_ttl(self):
        repo = self._repo()
        card = _make_card(card_type="key_moment")
        run(repo.upsert_card(card))
        doc = run(repo.get_card(card.card_id, "match01"))
        assert doc is not None
        assert "ttl" not in doc

    def test_custom_ttl_applied(self):
        repo = self._repo()
        card = _make_card(card_type="stat")
        run(repo.upsert_card(card, ttl=3600))
        doc = run(repo.get_card(card.card_id, "match01"))
        assert doc["ttl"] == 3600


# ---------------------------------------------------------------------------
# NarrationCacheRepository — round-trip
# ---------------------------------------------------------------------------

class TestNarrationCacheRepository:
    def test_upsert_and_get(self):
        repo = NarrationCacheRepository(FakeCosmosContainer())
        resp = _make_narrator_response()
        run(repo.upsert_response(resp))
        doc = run(repo.get_response(resp.profile_key, resp.moment_id))
        assert doc is not None
        assert doc["headline"] == "Goal!"

    def test_missing_returns_none(self):
        repo = NarrationCacheRepository(FakeCosmosContainer())
        result = run(repo.get_response("no.key.here.x", "m-0001"))
        assert result is None


# ---------------------------------------------------------------------------
# CosmosRepositories factory
# ---------------------------------------------------------------------------

class TestCosmosRepositories:
    def test_factory_creates_all_repos(self):
        repos = CosmosRepositories()
        assert repos.match_state_snapshots is not None
        assert repos.key_moments is not None
        assert repos.narration_cache is not None
        assert repos.overlay_cards is not None
        assert repos.audit_log is not None
        assert repos.corrections is not None

    def test_audit_log_create_only_via_factory(self):
        repos = CosmosRepositories()
        with pytest.raises(PermissionError):
            run(repos.audit_log._write_with_retry("upsert", {"id": "x", "match_id": "m"}))
