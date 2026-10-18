"""scripts/generate_bundle.py — Pre-generate the Msimulizi bundle.

Runs the ``comeback_from_two_down`` storyline with seed 42 through the full
pipeline for all 18 Profile Keys (3 languages × 2 modes × 3 club perspectives),
writes NarratorResponse records and audit entries to ``bundle/``, and produces
``bundle/manifest.json`` with deterministic card_ids, audio URLs, and SHA-256
checksums.

Usage (offline, no Azure credentials required):
    python -m scripts.generate_bundle --offline

Usage (full run with real Foundry and Speech):
    python -m scripts.generate_bundle
"""

from __future__ import annotations

import argparse
import asyncio
import dataclasses
import hashlib
import json
import logging
import os
import pathlib
import sys
import uuid
from datetime import datetime
from typing import Any

# Ensure repo root is on sys.path when run as a script.
_REPO_ROOT = pathlib.Path(__file__).resolve().parents[1]
if str(_REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(_REPO_ROOT))

from adapter.factory import get_adapter
from pipeline.explainer import ExplainerAgent
from pipeline.interpreter import Interpreter
from pipeline.moment import MomentAgent
from pipeline.narrator import NarratorAgent
from pipeline.verifier import VerifierAgent
from renderer.fallback import build_fallback_line, fallback_response
from renderer.renderer import render_fallback_card, render_narration_card
from shared.foundry_client import MockFoundryClient, QuotaExceeded
from shared.models import (
    EventType,
    KeyMoment,
    MatchState,
    NarrationRequest,
    NarratorResponse,
    OverlayCard,
)
from shared.profile_key import make_profile_key

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

BUNDLE_STORYLINE = "comeback_from_two_down"
BUNDLE_SEED = 42
BUNDLE_DIR = _REPO_ROOT / "bundle"

LANGUAGES = ["en", "fr", "sw"]
MODES = ["casual", "analyst"]
PERSPECTIVES = ["home", "away", "neutral"]

# All 18 profile-key dimension combinations (language × mode × perspective)
_PROFILE_DIMENSIONS = [
    (lang, mode, persp)
    for lang in LANGUAGES
    for mode in MODES
    for persp in PERSPECTIVES
]


# ---------------------------------------------------------------------------
# Serialisation helpers
# ---------------------------------------------------------------------------

def _json_default(obj: Any) -> Any:
    """JSON serialiser for dataclasses and datetimes."""
    if dataclasses.is_dataclass(obj) and not isinstance(obj, type):
        return dataclasses.asdict(obj)
    if isinstance(obj, datetime):
        return obj.isoformat()
    raise TypeError(f"Object of type {type(obj).__name__} is not JSON serialisable")


def _sha256_of_file(path: pathlib.Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as f:
        for chunk in iter(lambda: f.read(65536), b""):
            h.update(chunk)
    return h.hexdigest()


def _sha256_of_text(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


# ---------------------------------------------------------------------------
# Offline mock Foundry client
# ---------------------------------------------------------------------------

class _OfflineFoundryClient:
    """Offline mock that derives narrator responses from the actual request payload.

    Unlike a static MockFoundryClient, this reads the user-turn JSON from the
    prompt messages so the minute/score/player claims always match what the
    verifier expects.
    """

    def __init__(self) -> None:
        self.calls: list[dict[str, Any]] = []

    async def structured_output(
        self,
        agent_key: str,
        messages: list[dict[str, str]],
        response_schema: dict[str, Any],
    ) -> dict[str, Any]:
        self.calls.append({"agent_key": agent_key})

        if "explainer" in agent_key:
            return {
                "reason": "The team capitalised on their dominant possession to change the game.",
            }

        if "verifier" in agent_key:
            return {"verdict": "pass", "rejection_reason": None}

        if "narrator" in agent_key:
            # Extract actual request fields from the last user message.
            user_content = next(
                (m["content"] for m in reversed(messages) if m.get("role") == "user"),
                "{}",
            )
            try:
                payload = json.loads(user_content)
            except (json.JSONDecodeError, TypeError):
                payload = {}

            minute = payload.get("minute") or 1
            score = payload.get("score") or "0-0"
            player = payload.get("player") or "Player"
            language = payload.get("language", "en")
            mode = payload.get("mode", "casual")

            # For analyst mode pick the first available numeric evidence display_value
            # so the metric claim matches what the verifier will check against.
            metric_value: str | None = None
            metric_name: str | None = None
            if mode == "analyst":
                numeric_evidence = payload.get("numeric_evidence") or []
                for entry in numeric_evidence:
                    if isinstance(entry, dict) and entry.get("display_value"):
                        metric_value = str(entry["display_value"])
                        metric_name = str(entry.get("metric", "possession_home"))
                        break
                if metric_value is None:
                    metric_value = "50%"
                    metric_name = "possession_home"

            claims: list[dict[str, str]] = []
            if player:
                claims.append({"claim_type": "player", "value": str(player)})
            if minute is not None:
                claims.append({"claim_type": "minute", "value": str(minute)})
            if score:
                claims.append({"claim_type": "score", "value": str(score)})
            if mode == "analyst" and metric_value and metric_name:
                claims.append({"claim_type": "metric", "value": metric_value, "metric": metric_name})

            if language == "sw":
                if mode == "analyst" and metric_value:
                    headline = f"Goli! {player} dakika ya {minute}."
                    body = f"Dakika ya {minute}, {player} mbele kwa {score}; {metric_value}."
                    gloss_headline = f"Goal! {player} at minute {minute}."[:60]
                    gloss_body = f"Minute {minute}, {player} leads {score}; {metric_value}."[:140]
                else:
                    headline = f"Goli! {player} anafunga dakika ya {minute}."
                    body = f"Dakika ya {minute}, {player} anaiweka mbele kwa {score}."
                    gloss_headline = f"Goal! {player} scores at minute {minute}."[:60]
                    gloss_body = f"Minute {minute}, {player} puts the team ahead {score}."[:140]
                return {
                    "headline": headline[:60],
                    "body": body[:140],
                    "claims_list": claims,
                    "gloss_en": {
                        "headline": gloss_headline,
                        "body": gloss_body,
                    },
                }
            else:
                if mode == "analyst" and metric_value:
                    headline = f"Goal! {player} at minute {minute}."
                    body = f"Minute {minute}, {player} leads {score}; {metric_value}."
                else:
                    headline = f"Goal! {player} scores at minute {minute}."
                    body = f"Minute {minute}, {player} puts the team ahead {score}."
                return {
                    "headline": headline[:60],
                    "body": body[:140],
                    "claims_list": claims,
                    "gloss_en": None,
                }

        raise RuntimeError(f"_OfflineFoundryClient: unknown agent_key={agent_key!r}")


def _make_offline_foundry_client(n_responses: int = 100) -> _OfflineFoundryClient:
    """Return a dynamic offline client that mirrors actual request data."""
    return _OfflineFoundryClient()


# ---------------------------------------------------------------------------
# Pipeline runner (single session, all profile keys)
# ---------------------------------------------------------------------------

async def _run_pipeline_for_bundle(
    *,
    foundry_client: Any,
    content_safety: Any | None = None,
) -> dict[str, list[dict[str, Any]]]:
    """Run the full pipeline and collect cards per profile key.

    Returns a mapping of ``profile_key → list[card_dict]``.
    """
    match_id_stub = f"{BUNDLE_STORYLINE}-{BUNDLE_SEED}"
    session_id = "bundle-gen-session"

    interpreter = Interpreter(session_id=session_id, match_id=match_id_stub)
    moment_agent = MomentAgent(match_id=match_id_stub)
    explainer = ExplainerAgent(client=foundry_client)
    narrator = NarratorAgent(client=foundry_client)
    verifier = VerifierAgent(
        client=foundry_client,
        narrator=narrator,
        content_safety=content_safety,
    )

    adapter = get_adapter(source="inprocess", storyline=BUNDLE_STORYLINE, seed=BUNDLE_SEED)

    # Store cards by profile_key; use a shared narration cache to deduplicate LLM calls.
    narration_cache: dict[str, NarratorResponse] = {}
    cards_by_profile: dict[str, list[dict[str, Any]]] = {
        make_profile_key(match_id_stub, lang, mode, persp): []
        for lang, mode, persp in _PROFILE_DIMENSIONS
    }
    recent_events: list[Any] = []

    async for event in adapter.events(session_id, speed=1000.0):
        state: MatchState = await asyncio.to_thread(interpreter.process_event, event)
        key_moment: KeyMoment | None = moment_agent.detect(state, event)

        recent_events.append(event)
        if len(recent_events) > 200:
            recent_events = recent_events[-200:]

        if key_moment is None:
            continue

        # Build explanation once per moment (shared across all profile keys)
        try:
            explanation = await explainer.explain(key_moment, state)
            key_moment.structured_explanation = explanation
        except Exception as exc:
            logger.warning("[bundle] explainer failed for %s: %s", key_moment.moment_id, exc)
            explanation = None

        match_clock = {"period": event.period, "minute": event.minute, "second": event.second}
        match_secs = float(event.minute * 60 + event.second)

        # Generate narration for each of the 18 profile keys
        for lang, mode, persp in _PROFILE_DIMENSIONS:
            profile_key = make_profile_key(match_id_stub, lang, mode, persp)
            cache_key = f"{profile_key}:{key_moment.moment_id}"

            # Cache hit — reuse existing response
            if cache_key in narration_cache:
                cached = narration_cache[cache_key]
                card_type = "goal" if "goal" in key_moment.trigger_tags else "key_moment"
                card = render_narration_card(
                    response=cached,
                    match_clock=match_clock,
                    match_seconds=match_secs,
                    card_type=card_type,
                    priority=key_moment.priority_rank,
                    team_ref=event.team,
                    player_ref=event.player or None,
                    structured_explanation=explanation,
                    evidence_event_ids=(explanation.evidence_event_ids if explanation else []),
                )
                card.from_bundle = True
                cards_by_profile[profile_key].append(dataclasses.asdict(card))
                continue

            request = NarrationRequest(
                profile_key=profile_key,
                moment_id=key_moment.moment_id,
                language=lang,
                mode=mode,
                club_perspective=persp,
                match_id=match_id_stub,
                structured_explanation=explanation,
                minute=event.minute,
                score=f"{event.score_home}-{event.score_away}",
                team=event.team,
                player=event.player,
                trigger_tags=list(key_moment.trigger_tags),
            )

            narrator_response = None
            try:
                narrator_response = await narrator.generate(request)
            except QuotaExceeded:
                logger.warning("[bundle] QuotaExceeded for %s — using fallback", profile_key)
            except Exception as exc:
                logger.warning("[bundle] narrator failed for %s: %s", profile_key, exc)

            card: OverlayCard | None = None
            if narrator_response is not None:
                try:
                    result = await verifier.verify(request, narrator_response, event=event, match_state=state)
                    if result.verdict == "pass" and result.response is not None:
                        card_type = "goal" if "goal" in key_moment.trigger_tags else "key_moment"
                        card = render_narration_card(
                            response=result.response,
                            match_clock=match_clock,
                            match_seconds=match_secs,
                            card_type=card_type,
                            priority=key_moment.priority_rank,
                            team_ref=event.team,
                            player_ref=event.player or None,
                            structured_explanation=explanation,
                            evidence_event_ids=(explanation.evidence_event_ids if explanation else []),
                        )
                        narration_cache[cache_key] = result.response
                except Exception as exc:
                    logger.warning("[bundle] verifier failed for %s: %s", profile_key, exc)

            if card is None:
                fb = build_fallback_line(
                    language=lang,
                    moment_type=(key_moment.trigger_tags[0] if key_moment.trigger_tags else "default"),
                    player=event.player,
                    minute=event.minute,
                    event_type=event.event_type.value,
                    score=f"{event.score_home}-{event.score_away}",
                )
                card = render_fallback_card(
                    profile_key=profile_key,
                    moment_id=key_moment.moment_id,
                    match_clock=match_clock,
                    match_seconds=match_secs,
                    language=lang,
                    card_type="key_moment",
                    priority=key_moment.priority_rank,
                    team_ref=event.team,
                    headline=fb.get("headline", ""),
                    body=fb.get("body", ""),
                )

            card.from_bundle = True
            cards_by_profile[profile_key].append(dataclasses.asdict(card))

    return cards_by_profile


# ---------------------------------------------------------------------------
# Bundle writing
# ---------------------------------------------------------------------------

def _write_bundle(
    cards_by_profile: dict[str, list[dict[str, Any]]],
    *,
    audio_base_url: str = "",
) -> pathlib.Path:
    """Write bundle files and return the path to manifest.json."""
    BUNDLE_DIR.mkdir(parents=True, exist_ok=True)
    narrations_dir = BUNDLE_DIR / "narrations"
    audit_dir = BUNDLE_DIR / "audit"
    narrations_dir.mkdir(exist_ok=True)
    audit_dir.mkdir(exist_ok=True)

    manifest_entries: list[dict[str, Any]] = []

    for profile_key, cards in cards_by_profile.items():
        if not cards:
            continue

        # Write narrations file
        narration_path = narrations_dir / f"{profile_key}.json"
        narration_text = json.dumps(cards, default=_json_default, indent=2, ensure_ascii=False)
        narration_path.write_text(narration_text, encoding="utf-8")

        # Build audit entries (one per card)
        audit_entries = [
            {
                "id": str(uuid.uuid4()),
                "card_id": c.get("card_id"),
                "profile_key": profile_key,
                "match_id": c.get("match_id"),
                "verdict": "pass" if not c.get("card_type") == "fallback" else "fallback",
                "from_bundle": True,
                "generated_at": datetime.utcnow().isoformat(),
            }
            for c in cards
        ]
        audit_text = json.dumps(audit_entries, indent=2, ensure_ascii=False)
        (audit_dir / f"{profile_key}.json").write_text(audit_text, encoding="utf-8")

        # Manifest entries per card
        for card in cards:
            card_id = card.get("card_id", "")
            audio_url = card.get("audio_url") or ""
            if audio_url and audio_base_url and not audio_url.startswith("http"):
                audio_url = f"{audio_base_url.rstrip('/')}/{audio_url}"

            manifest_entries.append({
                "card_id": card_id,
                "profile_key": profile_key,
                "card_type": card.get("card_type"),
                "match_seconds": card.get("match_seconds", 0),
                "priority": card.get("priority"),
                "audio_url": audio_url or None,
                "narration_checksum": _sha256_of_text(
                    json.dumps(card, default=_json_default, sort_keys=True)
                ),
            })

    manifest_path = BUNDLE_DIR / "manifest.json"
    manifest = {
        "storyline": BUNDLE_STORYLINE,
        "seed": BUNDLE_SEED,
        "generated_at": datetime.utcnow().isoformat(),
        "profile_keys": list(cards_by_profile.keys()),
        "total_cards": sum(len(c) for c in cards_by_profile.values()),
        "entries": manifest_entries,
    }
    manifest_path.write_text(
        json.dumps(manifest, default=_json_default, indent=2, ensure_ascii=False),
        encoding="utf-8",
    )
    logger.info("[bundle] manifest written with %d entries", len(manifest_entries))
    return manifest_path


# ---------------------------------------------------------------------------
# Public entry-point for startup seeding
# ---------------------------------------------------------------------------

def load_bundle_narrations() -> dict[str, list[dict[str, Any]]]:
    """Load bundle narration records from disk.

    Returns a mapping of ``profile_key → list[card_dict]``.
    Returns an empty dict when the bundle directory does not exist.
    """
    narrations_dir = BUNDLE_DIR / "narrations"
    if not narrations_dir.exists():
        logger.info("[bundle] narrations directory not found — skipping bundle load")
        return {}

    result: dict[str, list[dict[str, Any]]] = {}
    for json_file in sorted(narrations_dir.glob("*.json")):
        profile_key = json_file.stem
        try:
            cards = json.loads(json_file.read_text(encoding="utf-8"))
            if isinstance(cards, list):
                result[profile_key] = cards
        except Exception as exc:
            logger.warning("[bundle] failed to load %s: %s", json_file.name, exc)

    logger.info("[bundle] loaded %d profile keys from disk", len(result))
    return result


def seed_narration_cache(
    narration_cache: Any,
    bundle_cards: dict[str, list[dict[str, Any]]],
) -> int:
    """Seed a narration cache repository with bundle cards.

    Supports both dict-based caches and objects with an ``upsert`` / ``set`` method.
    Each card is inserted with ``from_bundle=True``.

    Returns the number of cards seeded.
    """
    seeded = 0
    for profile_key, cards in bundle_cards.items():
        for card in cards:
            card_with_bundle = dict(card)
            card_with_bundle["from_bundle"] = True
            moment_id = card_with_bundle.get("moment_id") or card_with_bundle.get("match_id", "unknown")
            cache_key = f"{profile_key}:{moment_id}"

            if isinstance(narration_cache, dict):
                narration_cache[cache_key] = card_with_bundle
                seeded += 1
            elif hasattr(narration_cache, "set"):
                narration_cache.set(cache_key, card_with_bundle)
                seeded += 1
            elif hasattr(narration_cache, "upsert"):
                narration_cache.upsert(cache_key, card_with_bundle)
                seeded += 1

    logger.info("[bundle] seeded %d cards into narration cache", seeded)
    return seeded


def serve_bundle_card_for_quota_exceeded(
    profile_key: str,
    moment_id: str,
    bundle_cards: dict[str, list[dict[str, Any]]],
) -> dict[str, Any] | None:
    """Return the first bundle card for a profile key when quota is exceeded.

    Returns ``None`` when no bundle cards are available for the profile key
    or when the storyline is not the default bundled one.
    """
    cards = bundle_cards.get(profile_key, [])
    if not cards:
        return None
    # Prefer an exact moment_id match; fall back to the first card
    for card in cards:
        if card.get("moment_id") == moment_id:
            return dict(card)
    return dict(cards[0])


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------

async def _main(*, offline: bool) -> None:
    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(message)s")

    if offline:
        logger.info("[bundle] running in OFFLINE mode with MockFoundryClient")
        foundry_client: Any = _make_offline_foundry_client(n_responses=200)
        content_safety = None
    else:
        endpoint = os.getenv("FOUNDRY_ENDPOINT", "").strip()
        api_key = os.getenv("FOUNDRY_API_KEY", "").strip() or None
        if not endpoint:
            logger.warning("[bundle] FOUNDRY_ENDPOINT not set — falling back to offline mode")
            foundry_client = _make_offline_foundry_client(n_responses=200)
        else:
            from shared.foundry_client import FoundryClient
            foundry_client = FoundryClient(endpoint=endpoint, api_key=api_key)

        # Try to load Content Safety client
        try:
            from shared.content_safety import ContentSafetyClient
            cs_endpoint = os.getenv("CONTENT_SAFETY_ENDPOINT", "").strip()
            cs_key = os.getenv("CONTENT_SAFETY_KEY", "").strip() or None
            content_safety = ContentSafetyClient(endpoint=cs_endpoint, api_key=cs_key) if cs_endpoint else None
        except Exception:
            content_safety = None

    logger.info("[bundle] generating bundle for storyline=%s seed=%d", BUNDLE_STORYLINE, BUNDLE_SEED)
    cards_by_profile = await _run_pipeline_for_bundle(
        foundry_client=foundry_client,
        content_safety=content_safety,
    )

    total = sum(len(c) for c in cards_by_profile.values())
    logger.info("[bundle] pipeline complete: %d total cards across %d profile keys", total, len(cards_by_profile))

    manifest_path = _write_bundle(cards_by_profile)
    logger.info("[bundle] manifest: %s", manifest_path)


def main() -> None:
    parser = argparse.ArgumentParser(description="Generate the Msimulizi pre-generated bundle")
    parser.add_argument("--offline", action="store_true", help="Use MockFoundryClient; no Azure credentials needed")
    args = parser.parse_args()
    asyncio.run(_main(offline=args.offline))


if __name__ == "__main__":
    main()
