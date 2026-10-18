"""tests/test_bundle.py — Unit tests for the pre-generated bundle (Task 28).

Tests cover:
- load_bundle_narrations: loads cards from disk correctly
- seed_narration_cache: seeds a dict-based cache with from_bundle=True
- serve_bundle_card_for_quota_exceeded: returns bundle card on quota exceeded
- Cache-hit rendering: pipeline runner uses cache, no LLM calls
- Quota-exceeded fallback: QuotaExceeded triggers bundle card broadcast
"""

from __future__ import annotations

import asyncio
import dataclasses
import json
import pathlib
import tempfile
from typing import Any
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from scripts.generate_bundle import (
    load_bundle_narrations,
    seed_narration_cache,
    serve_bundle_card_for_quota_exceeded,
)
from shared.foundry_client import MockFoundryClient, QuotaExceeded


# ---------------------------------------------------------------------------
# Fixtures — minimal bundle on disk
# ---------------------------------------------------------------------------

@pytest.fixture
def tmp_bundle_dir(tmp_path: pathlib.Path) -> pathlib.Path:
    """Create a minimal bundle directory with one profile key's narrations."""
    narrations_dir = tmp_path / "narrations"
    narrations_dir.mkdir()
    audit_dir = tmp_path / "audit"
    audit_dir.mkdir()

    profile_key = "comeback-from-two-down-42.en.casual.neutral"
    cards = [
        {
            "card_id": "card-key_moment-abc123def456",
            "match_id": "comeback-from-two-down-42",
            "profile_key": profile_key,
            "moment_id": "comeback-from-two-down-42-km-0001",
            "match_clock": {"period": 1, "minute": 12, "second": 0},
            "match_seconds": 720.0,
            "display_duration_ms": 6000,
            "card_type": "key_moment",
            "priority": 1,
            "player_ref": "Juma Mwakazi",
            "team_ref": "Mombasa United",
            "text": {
                "en": {"headline": "Goal for Mombasa!", "body": "Juma Mwakazi opens the scoring."},
                "fr": {"headline": "But pour Mombasa!", "body": "Juma Mwakazi ouvre le score."},
                "sw": {"headline": "Goli la Mombasa!", "body": "Juma Mwakazi anafunga kwanza."},
            },
            "gloss_en": None,
            "structured_explanation": None,
            "evidence_event_ids": [],
            "stat_payload": {},
            "audio_url": None,
            "synthetic_ai_generated": True,
            "from_bundle": True,
        }
    ]
    (narrations_dir / f"{profile_key}.json").write_text(
        json.dumps(cards, indent=2), encoding="utf-8"
    )
    return tmp_path


# ---------------------------------------------------------------------------
# Tests: load_bundle_narrations
# ---------------------------------------------------------------------------

def test_load_bundle_narrations_returns_cards_by_profile_key(tmp_bundle_dir: pathlib.Path) -> None:
    with patch("scripts.generate_bundle.BUNDLE_DIR", tmp_bundle_dir):
        result = load_bundle_narrations()

    assert len(result) == 1
    profile_key = "comeback-from-two-down-42.en.casual.neutral"
    assert profile_key in result
    assert len(result[profile_key]) == 1
    assert result[profile_key][0]["card_id"] == "card-key_moment-abc123def456"


def test_load_bundle_narrations_returns_empty_when_no_dir() -> None:
    with patch("scripts.generate_bundle.BUNDLE_DIR", pathlib.Path("/nonexistent/path/bundle")):
        result = load_bundle_narrations()
    assert result == {}


def test_load_bundle_narrations_skips_invalid_json(tmp_path: pathlib.Path) -> None:
    narrations_dir = tmp_path / "narrations"
    narrations_dir.mkdir()
    (narrations_dir / "bad.profile.key.en.json").write_text("not valid json", encoding="utf-8")

    with patch("scripts.generate_bundle.BUNDLE_DIR", tmp_path):
        result = load_bundle_narrations()

    # The bad file is skipped; no error raised
    assert isinstance(result, dict)


# ---------------------------------------------------------------------------
# Tests: seed_narration_cache
# ---------------------------------------------------------------------------

def test_seed_narration_cache_inserts_with_from_bundle_flag(tmp_bundle_dir: pathlib.Path) -> None:
    with patch("scripts.generate_bundle.BUNDLE_DIR", tmp_bundle_dir):
        bundle_cards = load_bundle_narrations()

    cache: dict[str, Any] = {}
    seeded = seed_narration_cache(cache, bundle_cards)

    assert seeded == 1
    assert len(cache) == 1

    key = next(iter(cache))
    cached_card = cache[key]
    assert cached_card["from_bundle"] is True


def test_seed_narration_cache_with_empty_bundle() -> None:
    cache: dict[str, Any] = {}
    seeded = seed_narration_cache(cache, {})
    assert seeded == 0
    assert cache == {}


def test_seed_narration_cache_supports_set_interface() -> None:
    """Cache objects with a .set() method are supported."""
    class MockCache:
        def __init__(self) -> None:
            self.data: dict[str, Any] = {}

        def set(self, key: str, value: Any) -> None:
            self.data[key] = value

    mock_cache = MockCache()
    bundle_cards = {
        "match-1.en.casual.neutral": [
            {
                "card_id": "card-abc",
                "match_id": "match-1",
                "profile_key": "match-1.en.casual.neutral",
                "moment_id": "match-1-km-0001",
                "card_type": "key_moment",
                "from_bundle": True,
            }
        ]
    }
    seeded = seed_narration_cache(mock_cache, bundle_cards)
    assert seeded == 1
    assert len(mock_cache.data) == 1


# ---------------------------------------------------------------------------
# Tests: serve_bundle_card_for_quota_exceeded
# ---------------------------------------------------------------------------

def test_serve_bundle_card_returns_card_on_quota_exceeded() -> None:
    profile_key = "match-1.en.casual.neutral"
    bundle_cards: dict[str, list[dict[str, Any]]] = {
        profile_key: [
            {
                "card_id": "card-abc",
                "match_id": "match-1",
                "moment_id": "match-1-km-0001",
                "card_type": "key_moment",
                "from_bundle": True,
            }
        ]
    }

    result = serve_bundle_card_for_quota_exceeded(profile_key, "match-1-km-0001", bundle_cards)
    assert result is not None
    assert result["card_id"] == "card-abc"
    assert result["from_bundle"] is True


def test_serve_bundle_card_returns_first_card_when_moment_id_not_found() -> None:
    profile_key = "match-1.en.casual.neutral"
    bundle_cards = {
        profile_key: [
            {"card_id": "card-first", "moment_id": "km-0001", "from_bundle": True}
        ]
    }
    result = serve_bundle_card_for_quota_exceeded(profile_key, "km-9999", bundle_cards)
    assert result is not None
    assert result["card_id"] == "card-first"


def test_serve_bundle_card_returns_none_when_profile_key_missing() -> None:
    result = serve_bundle_card_for_quota_exceeded("nonexistent.key", "km-001", {})
    assert result is None


# ---------------------------------------------------------------------------
# Tests: cache-hit rendering skips LLM
# ---------------------------------------------------------------------------

def test_pipeline_runner_uses_narration_cache_and_skips_narrator_verifier() -> None:
    """When narration_cache is pre-seeded, narrator and verifier LLM calls are skipped.

    The explainer still runs (it builds the structured explanation before the
    narrator cache check), but narrator_en_fr, narrator_sw, and verifier calls
    must be absent because the cache hit short-circuits that path.
    """
    from api.pipeline_runner import run_pipeline_session
    from api.websocket import WebSocketManager

    mock_foundry = MockFoundryClient()
    # Provide enough explainer responses (cache hit path still runs the explainer)
    for _ in range(50):
        mock_foundry.add_response("explainer", {
            "theme": "control_vs_chaos",
            "reason": "The home team dominated possession.",
            "numeric_evidence": [],
            "evidence_event_ids": [],
            "partially_grounded": False,
        })

    ws_manager = WebSocketManager()

    # Pre-seed narration cache for all moment IDs the pipeline might generate
    narration_cache: dict[str, Any] = {}
    bundle_entry = {
        "card_id": "card-bundle-test",
        "match_id": "comeback-from-two-down-42",
        "profile_key": "comeback-from-two-down-42.en.casual.neutral",
        "card_type": "key_moment",
        "text": {"en": {"headline": "Test bundle card", "body": "From bundle."}},
        "gloss_en": None,
        "from_bundle": True,
    }
    for km_seq in range(1, 30):
        moment_id = f"comeback-from-two-down-42-km-{km_seq:04d}"
        cache_key = f"comeback-from-two-down-42.en.casual.neutral:{moment_id}"
        narration_cache[cache_key] = dict(bundle_entry, moment_id=moment_id)

    cards_received: list[Any] = []

    async def mock_broadcast_card(match_id: str, card: Any, session_id: str) -> None:
        cards_received.append(card)

    async def mock_broadcast_clock(payload: Any, match_id: str) -> None:
        pass

    ws_manager.broadcast_card = mock_broadcast_card  # type: ignore[method-assign]
    ws_manager.broadcast_clock = mock_broadcast_clock  # type: ignore[method-assign]

    async def _run() -> None:
        await run_pipeline_session(
            "test-session",
            "comeback-from-two-down-42",
            storyline="comeback_from_two_down",
            seed=42,
            speed=1000.0,
            language="en",
            mode="casual",
            ws_manager=ws_manager,
            foundry_client=mock_foundry,
            narration_cache=narration_cache,
            bundle_cards=None,
        )

    asyncio.run(_run())

    # Narrator and verifier must not have been called — only explainer is allowed
    narrator_calls = [c for c in mock_foundry.calls if c["agent_key"] in ("narrator_en_fr", "narrator_sw")]
    verifier_calls = [c for c in mock_foundry.calls if c["agent_key"] == "verifier"]
    assert narrator_calls == [], (
        f"Expected no narrator LLM calls on cache hit, got {len(narrator_calls)}"
    )
    assert verifier_calls == [], (
        f"Expected no verifier LLM calls on cache hit, got {len(verifier_calls)}"
    )
    # Bundle cards must have been broadcast
    bundle_hits = [c for c in cards_received if c.get("from_bundle") is True]
    assert bundle_hits, "Expected bundle cards to be broadcast from cache"


# ---------------------------------------------------------------------------
# Tests: quota-exceeded fallback
# ---------------------------------------------------------------------------

def test_pipeline_runner_serves_bundle_on_quota_exceeded() -> None:
    """When QuotaExceeded is raised, the pipeline broadcasts the bundle card."""
    from api.pipeline_runner import run_pipeline_session
    from api.websocket import WebSocketManager

    mock_foundry = MockFoundryClient()
    # Make the narrator always raise QuotaExceeded
    for _ in range(50):
        mock_foundry.set_raise("narrator_en_fr", QuotaExceeded("test quota exceeded"))
        mock_foundry.set_raise("narrator_sw", QuotaExceeded("test quota exceeded"))

    # Add explainer and verifier responses so those stages succeed
    for _ in range(50):
        mock_foundry.add_response("explainer", {
            "theme": "control_vs_chaos",
            "reason": "Test reason.",
            "numeric_evidence": [],
            "evidence_event_ids": [],
            "partially_grounded": False,
        })

    ws_manager = WebSocketManager()
    cards_received: list[Any] = []

    async def mock_broadcast_card(match_id: str, card: Any, session_id: str) -> None:
        cards_received.append(card)

    async def mock_broadcast_clock(payload: Any, match_id: str) -> None:
        pass

    ws_manager.broadcast_card = mock_broadcast_card  # type: ignore[method-assign]
    ws_manager.broadcast_clock = mock_broadcast_clock  # type: ignore[method-assign]

    # Pre-build bundle cards that should be served on QuotaExceeded
    bundle_cards: dict[str, list[dict[str, Any]]] = {
        "comeback-from-two-down-42.en.casual.neutral": [
            {
                "card_id": "card-bundle-quota-test",
                "match_id": "comeback-from-two-down-42",
                "profile_key": "comeback-from-two-down-42.en.casual.neutral",
                "moment_id": "comeback-from-two-down-42-km-0001",
                "card_type": "key_moment",
                "text": {"en": {"headline": "Bundle fallback", "body": "From bundle."}},
                "gloss_en": None,
                "from_bundle": True,
            }
        ]
    }

    async def _run() -> None:
        await run_pipeline_session(
            "test-quota-session",
            "comeback-from-two-down-42",
            storyline="comeback_from_two_down",
            seed=42,
            speed=1000.0,
            language="en",
            mode="casual",
            ws_manager=ws_manager,
            foundry_client=mock_foundry,
            narration_cache=None,
            bundle_cards=bundle_cards,
        )

    asyncio.run(_run())

    # At least one bundle card should have been broadcast on quota exceeded
    bundle_hits = [c for c in cards_received if c.get("from_bundle") is True]
    assert bundle_hits, (
        f"Expected bundle cards to be broadcast on QuotaExceeded. "
        f"Got {len(cards_received)} total cards, none with from_bundle=True."
    )
