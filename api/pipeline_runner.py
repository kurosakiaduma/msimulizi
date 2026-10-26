"""api/pipeline_runner.py — asyncio pipeline driver for a single replay session.

This module drives one match from the adapter through every pipeline stage and
pushes resulting OverlayCards to the WebSocket gateway.

Audio integration:
* Broadcast the approved caption first.
* Schedule TTS in a background task so synthesis does not block match playback.
* Publish audio updates through the existing WebSocket manager using the
  existing four-field audio_update payload.
* Cancel session-owned audio wrapper tasks when the session is cancelled.

It remains separate from orchestrator.py, which holds the Agent-Framework
workflow declaration. This file owns the per-session asyncio task and the
stage-by-stage wiring.
"""

from __future__ import annotations

import asyncio
import dataclasses
import logging
import os
import re
import time
from typing import Any

from adapter.factory import get_adapter
from pipeline.explainer import ExplainerAgent
from pipeline.interpreter import Interpreter
from pipeline.moment import MomentAgent
from pipeline.narrator import NarratorAgent
from pipeline.personaliser import PersonaliserAgent
from pipeline.verifier import VerifierAgent
from renderer.fallback import build_fallback_line
from renderer.renderer import render_fallback_card, render_narration_card
from renderer.tts import synthesize_card_audio
from shared.foundry_client import QuotaExceeded
from shared.models import EventType, GlossEn, KeyMoment, MatchState, OverlayCard
from shared.observability import metrics

logger = logging.getLogger(__name__)

# A process-level strong-reference registry keeps fire-and-forget audio tasks
# alive even after a session pipeline finishes. Per-session sets are still used
# to cancel work if that session is cancelled.
_BACKGROUND_AUDIO_TASKS: set[asyncio.Task[Any]] = set()


# ---------------------------------------------------------------------------
# General helpers
# ---------------------------------------------------------------------------

def _match_clock(state: MatchState) -> dict[str, int]:
    return {
        "period": state.sequence_number and 1 or 1,
        "minute": state.minute,
        "second": state.second,
    }


def _match_seconds(state: MatchState) -> float:
    return float(state.minute * 60 + state.second)


def _card_to_dict(card: OverlayCard) -> dict[str, Any]:
    """Convert an OverlayCard dataclass to a JSON-serialisable dictionary."""
    return dataclasses.asdict(card)


def _find_bundle_card(
    bundle_cards: dict[str, Any] | None,
    *,
    profile_key: str,
    match_seconds: float,
    card_type: str,
) -> dict[str, Any] | None:
    """Find a pre-generated card when bundle records lack a moment ID."""
    if not bundle_cards:
        return None

    cards = bundle_cards.get(profile_key)
    if not isinstance(cards, list):
        return None

    for candidate in cards:
        if not isinstance(candidate, dict):
            continue
        candidate_seconds = candidate.get("match_seconds")
        if (
            isinstance(candidate_seconds, (int, float))
            and float(candidate_seconds) == match_seconds
            and candidate.get("card_type") == card_type
        ):
            return candidate

    return None


def _read_field(obj: Any, *names: str, default: Any = None) -> Any:
    """Read the first available field from a dictionary or object."""
    for name in names:
        value = obj.get(name) if isinstance(obj, dict) else getattr(obj, name, None)
        if value is not None:
            return value
    return default


def _normalise_audio_key(value: Any) -> str:
    """Normalize an enum/string event tag to a stable snake-case key."""
    if value is None:
        return ""
    value = getattr(value, "value", value)
    if not isinstance(value, str):
        value = getattr(value, "name", value)
    return re.sub(r"[^a-z0-9]+", "_", str(value).strip().lower()).strip("_")


def _audio_event_key(event: Any, key_moment: KeyMoment) -> str:
    """Resolve emotion policy from verified event/moment fields, not prose."""
    aliases = {
        "equalizer": "equaliser",
        "equalizer_goal": "equaliser",
        "equaliser_goal": "equaliser",
        "goal_scored": "goal",
        "scored_goal": "goal",
        "redcard": "red_card",
        "card_red": "red_card",
        "bigchance": "big_chance",
        "momentum_shift": "momentum_swing",
    }

    raw_tags = getattr(key_moment, "trigger_tags", None) or []
    if isinstance(raw_tags, str):
        raw_tags = [raw_tags]

    tags: set[str] = set()
    for tag in raw_tags:
        normalized = _normalise_audio_key(tag)
        tags.add(aliases.get(normalized, normalized))

    # Prefer a specific moment over a generic goal tag.
    for candidate in (
        "equaliser",
        "red_card",
        "big_chance",
        "momentum_swing",
        "goal",
    ):
        if candidate in tags:
            return candidate

    event_key = _normalise_audio_key(getattr(event, "event_type", None))
    event_key = aliases.get(event_key, event_key)
    if event_key in {
        "goal", "equaliser", "red_card", "big_chance", "momentum_swing"
    }:
        return event_key

    # In particular, do not assume an ordinary card is a red card.
    return event_key or "unknown"


def _audio_card_payload(
    card: Any,
    *,
    session_id: str,
    language: str,
    match_seconds: float,
    event: Any,
    key_moment: KeyMoment,
    narration_request: Any,
) -> dict[str, Any]:
    """Copy the card and attach trusted context required by renderer.tts."""
    if isinstance(card, dict):
        payload = dict(card)
    elif dataclasses.is_dataclass(card):
        payload = dataclasses.asdict(card)
    else:
        payload = dict(vars(card)) if hasattr(card, "__dict__") else {}

    card_id = _read_field(card, "card_id", default=payload.get("card_id"))
    if not card_id:
        stable_part = (
            getattr(key_moment, "moment_id", None)
            or getattr(event, "event_id", None)
            or f"{session_id}:{int(match_seconds)}"
        )
        card_id = str(stable_part)

    payload["card_id"] = str(card_id)
    payload["language"] = language
    payload["match_seconds"] = float(match_seconds)
    payload["minute"] = int(getattr(event, "minute", 0) or 0)
    payload["event_type"] = _audio_event_key(event, key_moment)

    # Only use perspective that a domain object explicitly provides. Never
    # infer a viewer's supported club from profile_key or narration wording.
    perspective = (
        _read_field(
            narration_request,
            "viewer_perspective", "perspective", "supporter_perspective",
        )
        or _read_field(
            key_moment,
            "viewer_perspective", "perspective", "supporter_perspective",
        )
        or _read_field(
            card,
            "viewer_perspective", "perspective", "supporter_perspective",
        )
        or "neutral"
    )
    payload["viewer_perspective"] = _normalise_audio_key(perspective) or "neutral"
    return payload


def _schedule_card_audio(
    *,
    card: Any,
    session_id: str,
    match_id: str,
    language: str,
    match_seconds: float,
    event: Any,
    key_moment: KeyMoment,
    narration_request: Any,
    ws_manager: Any,
    tts_client: Any,
    audio_tasks: set[asyncio.Task[Any]],
) -> None:
    """Schedule a single TTS render after its caption has been broadcast."""
    if tts_client is None or ws_manager is None:
        return

    audio_card = _audio_card_payload(
        card,
        session_id=session_id,
        language=language,
        match_seconds=match_seconds,
        event=event,
        key_moment=key_moment,
        narration_request=narration_request,
    )

    async def publish_audio_update(payload: dict[str, Any]) -> None:
        # Send the four-field audio_update as a top-level WebSocket message.
        # broadcast_clock() wraps payloads in clock_update and is not valid here.
        await ws_manager.broadcast_audio_update(
            payload,
            session_id=session_id,
            match_id=match_id,
        )

    async def render_audio() -> None:
        try:
            # Delegates to the registered AudioService singleton. Publication is
            # owned by the facade; do not broadcast a second audio_update here.
            await synthesize_card_audio(
                audio_card,
                synthesizer=tts_client,
                language=language,
                publisher=publish_audio_update,
            )
        except asyncio.CancelledError:
            raise
        except Exception:
            # TTS must never retract or delay the approved caption.
            logger.exception(
                "[audio] background synthesis failed session=%s card_id=%s",
                session_id,
                audio_card.get("card_id"),
            )

    task = asyncio.create_task(
        render_audio(),
        name=f"audio-{session_id}-{audio_card['card_id']}",
    )
    audio_tasks.add(task)
    _BACKGROUND_AUDIO_TASKS.add(task)
    task.add_done_callback(audio_tasks.discard)
    task.add_done_callback(_BACKGROUND_AUDIO_TASKS.discard)


async def _cancel_audio_tasks(
    audio_tasks: set[asyncio.Task[Any]],
    *,
    session_id: str,
) -> None:
    """Cancel and drain all audio wrapper tasks owned by a cancelled session."""
    tasks = tuple(audio_tasks)
    if not tasks:
        return

    logger.info(
        "[audio] cancelling %d background task(s) for session=%s",
        len(tasks),
        session_id,
    )
    for task in tasks:
        task.cancel()

    await asyncio.gather(*tasks, return_exceptions=True)
    audio_tasks.clear()


# ---------------------------------------------------------------------------
# Main pipeline driver
# ---------------------------------------------------------------------------

async def run_pipeline_session(
    session_id: str,
    match_id: str,
    *,
    storyline: str = "comeback_from_two_down",
    seed: int = 42,
    speed: float = 1.0,
    language: str = "en",
    mode: str = "casual",
    ws_manager: Any | None = None,
    foundry_client: Any | None = None,
    tts_client: Any | None = None,
    content_safety: Any | None = None,
    narration_cache: dict[str, Any] | None = None,
    bundle_cards: dict[str, Any] | None = None,
) -> None:
    """Drive one synthetic match session through the full pipeline.

    Captions are broadcast immediately. TTS runs asynchronously after the
    caption is sent and publishes an audio_update when rendering completes.
    """
    logger.info(
        "[pipeline] session=%s match=%s storyline=%s seed=%d speed=%.1fx lang=%s mode=%s",
        session_id, match_id, storyline, seed, speed, language, mode,
    )

    # ------------------------------------------------------------------
    # Build the pipeline agents
    # ------------------------------------------------------------------
    interpreter = Interpreter(session_id=session_id, match_id=match_id)
    moment_agent = MomentAgent(match_id=match_id)
    personaliser = PersonaliserAgent(language=language, mode=mode)
    explainer = ExplainerAgent(client=foundry_client)
    narrator = NarratorAgent(client=foundry_client)
    verifier = VerifierAgent(
        client=foundry_client,
        narrator=narrator,
        content_safety=content_safety,
    )

    # ------------------------------------------------------------------
    # Obtain the adapter
    # ------------------------------------------------------------------
    event_source = os.getenv("EVENT_SOURCE", "inprocess")
    adapter = get_adapter(
        source=event_source,
        storyline=storyline,
        seed=seed,
    )

    # ------------------------------------------------------------------
    # Event loop
    # ------------------------------------------------------------------
    cards_emitted = 0
    # Keep strong references to audio tasks until they finish. On session
    # cancellation, cancel and drain these wrappers explicitly.
    audio_tasks: set[asyncio.Task[Any]] = set()
    recent_events: list[Any] = []

    # Use one epoch anchor for the whole replay so the browser can derive the
    # same continuously advancing match clock between event notifications.
    clock_anchor_wall = time.time() * 1000.0
    clock_anchor_match = 0.0

    try:
        async for event in adapter.events(session_id, speed=speed):
            # Record wall time at event receipt for end-to-end card latency.
            _event_wall = time.monotonic()

            # ----------------------------------------------------------
            # 1. Interpreter — update rolling match state
            # ----------------------------------------------------------
            state: MatchState = await asyncio.to_thread(
                interpreter.process_event,
                event,
            )

            # ----------------------------------------------------------
            # 2. Broadcast clock update + event dot
            # ----------------------------------------------------------
            clock_payload = {
                "period": event.period,
                "minute": event.minute,
                "second": event.second,
                "score_home": event.score_home,
                "score_away": event.score_away,
                "match_seconds": float(event.minute * 60 + event.second),
                "speed": speed,
                "anchor_wall": clock_anchor_wall,
                "anchor_match": clock_anchor_match,
                "momentum_home": round(state.momentum_home, 1),
                "momentum_away": round(state.momentum_away, 1),
                "possession_home": round(state.possession_home, 3),
                "xg_home": round(state.xg_home, 2),
                "xg_away": round(state.xg_away, 2),
                "field_tilt_home": round(state.field_tilt_home, 3),
                "field_tilt_away": round(state.field_tilt_away, 3),
                "tempo": round(state.tempo, 2),
            }
            if ws_manager is not None:
                await ws_manager.broadcast_clock(clock_payload, match_id=match_id)

                event_dot = {
                    "type": "event",
                    "event_id": event.event_id,
                    "x": event.x_start,
                    "y": event.y_start,
                    "event_type": event.event_type.value,
                    "team": event.team,
                    "player": event.player,
                    "minute": event.minute,
                    "outcome": event.outcome,
                }
                await ws_manager.broadcast_clock(event_dot, match_id=match_id)

            # ----------------------------------------------------------
            # 3. Moment — detect key moments
            # ----------------------------------------------------------
            key_moment: KeyMoment | None = moment_agent.detect(state, event)

            recent_events.append(event)
            if len(recent_events) > 200:
                recent_events = recent_events[-200:]

            if key_moment is None:
                # No moment: emit lightweight score updates for goals/cards.
                if event.event_type in {EventType.goal, EventType.card}:
                    score_msg = {
                        "type": "score_update",
                        "session_id": session_id,
                        "match_id": match_id,
                        "minute": event.minute,
                        "score_home": event.score_home,
                        "score_away": event.score_away,
                        "event_type": event.event_type.value,
                        "player": event.player,
                        "team": event.team,
                    }
                    if ws_manager is not None:
                        await ws_manager.broadcast_clock(score_msg, match_id=match_id)
                continue

            logger.info(
                "[moment] %s tags=%s priority=%d min=%d",
                key_moment.moment_id,
                key_moment.trigger_tags,
                key_moment.priority_rank,
                key_moment.minute,
            )

            # ----------------------------------------------------------
            # 4. Personaliser — build NarrationRequest
            # ----------------------------------------------------------
            narration_request = personaliser.prepare(
                key_moment,
                event=event,
                match_id=match_id,
            )
            if narration_request is None:
                # Already emitted/cached for this profile key.
                continue

            # ----------------------------------------------------------
            # 5. Explainer — build structured explanation
            # ----------------------------------------------------------
            try:
                explanation = await explainer.explain(key_moment, state)
                key_moment.structured_explanation = explanation
                narration_request.structured_explanation = explanation
                logger.info(
                    "[explainer] theme=%s grounded=%s",
                    explanation.theme,
                    not explanation.partially_grounded,
                )
            except Exception as exc:  # pragma: no cover - runtime-dependent
                logger.warning("[explainer] failed: %s", exc)
                explanation = None

            # ----------------------------------------------------------
            # 6. Narrator — generate narration
            # ----------------------------------------------------------
            narrator_response = None
            _quota_exceeded = False
            card: OverlayCard | None = None

            _cache_key = f"{narration_request.profile_key}:{narration_request.moment_id}"
            _match_seconds = float(event.minute * 60 + event.second)
            _card_type = (
                "goal"
                if "goal" in key_moment.trigger_tags
                else "key_moment"
            )

            cached = (
                narration_cache.get(_cache_key)
                if narration_cache is not None
                else None
            )
            if cached is None:
                cached = _find_bundle_card(
                    bundle_cards,
                    profile_key=narration_request.profile_key,
                    match_seconds=_match_seconds,
                    card_type=_card_type,
                )

            if cached is not None:
                logger.info("[narrator] cache hit for %s", _cache_key)
                card_type = _card_type
                match_clock_dict = {
                    "period": event.period,
                    "minute": event.minute,
                    "second": event.second,
                }
                match_secs = _match_seconds

                from shared.models import GlossEn as _GlossEn
                from shared.models import NarratorResponse as _NR
                from renderer.renderer import render_narration_card as _rnc

                text = cached.get("text") or {
                    "en": {
                        "headline": cached.get("headline", ""),
                        "body": cached.get("body", ""),
                    }
                }
                gloss_raw = cached.get("gloss_en")
                gloss_en = (
                    _GlossEn(
                        headline=gloss_raw.get("headline", ""),
                        body=gloss_raw.get("body", ""),
                    )
                    if isinstance(gloss_raw, dict)
                    else None
                )

                _nr = _NR(
                    profile_key=narration_request.profile_key,
                    moment_id=narration_request.moment_id,
                    headline=(
                        text.get("en", {}).get("headline", "")
                        or text.get(narration_request.language, {}).get("headline", "")
                    ),
                    body=(
                        text.get("en", {}).get("body", "")
                        or text.get(narration_request.language, {}).get("body", "")
                    ),
                    claims_list=[],
                    gloss_en=gloss_en,
                )
                card = _rnc(
                    response=_nr,
                    match_clock=match_clock_dict,
                    match_seconds=match_secs,
                    card_type=card_type,
                    priority=key_moment.priority_rank,
                    team_ref=event.team,
                    player_ref=event.player or None,
                    structured_explanation=explanation,
                    evidence_event_ids=(
                        explanation.evidence_event_ids if explanation else []
                    ),
                )
                card.from_bundle = cached.get("from_bundle", False)
                # Continue to the common broadcast/audio scheduling path.

            else:
                try:
                    narrator_response = await narrator.generate(narration_request)
                    logger.info(
                        "[narrator] headline=%r",
                        narrator_response.headline[:50],
                    )
                except QuotaExceeded:
                    logger.warning(
                        "[narrator] QuotaExceeded — trying bundle fallback"
                    )
                    metrics.record_quota_exceeded()
                    _quota_exceeded = True
                except Exception as exc:
                    logger.warning("[narrator] failed: %s", exc)

            # ----------------------------------------------------------
            # 7. Verifier — validate + emit card
            # ----------------------------------------------------------
            if card is None:
                match_clock_dict = {
                    "period": event.period,
                    "minute": event.minute,
                    "second": event.second,
                }
                match_secs = float(event.minute * 60 + event.second)

                # Quota exceeded — try the bundle first, then Fallback Line.
                if _quota_exceeded and bundle_cards is not None:
                    from scripts.generate_bundle import (
                        serve_bundle_card_for_quota_exceeded,
                    )

                    bundle_hit = serve_bundle_card_for_quota_exceeded(
                        narration_request.profile_key,
                        key_moment.moment_id,
                        bundle_cards,
                    )
                    if bundle_hit is not None:
                        logger.info(
                            "[narrator] serving bundle card on QuotaExceeded"
                        )
                        bundle_hit["from_bundle"] = True

                        if ws_manager is not None:
                            # Caption first; only after successful broadcast do
                            # we enqueue audio for this direct-dict branch.
                            await ws_manager.broadcast_card(
                                match_id=match_id,
                                card=bundle_hit,
                                session_id=session_id,
                            )
                            cards_emitted += 1
                            _schedule_card_audio(
                                card=bundle_hit,
                                session_id=session_id,
                                match_id=match_id,
                                language=narration_request.language,
                                match_seconds=match_secs,
                                event=event,
                                key_moment=key_moment,
                                narration_request=narration_request,
                                ws_manager=ws_manager,
                                tts_client=tts_client,
                                audio_tasks=audio_tasks,
                            )
                        continue

            if narrator_response is not None:
                try:
                    result = await verifier.verify(
                        narration_request,
                        narrator_response,
                        event=event,
                        match_state=state,
                    )
                    if result.verdict == "pass" and result.response is not None:
                        card_type = (
                            "goal"
                            if "goal" in key_moment.trigger_tags
                            else "key_moment"
                        )
                        card = render_narration_card(
                            response=result.response,
                            match_clock=match_clock_dict,
                            match_seconds=match_secs,
                            card_type=card_type,
                            priority=key_moment.priority_rank,
                            team_ref=event.team,
                            player_ref=event.player if event.player else None,
                            structured_explanation=explanation,
                            evidence_event_ids=(
                                explanation.evidence_event_ids if explanation else []
                            ),
                        )
                        logger.info("[verifier] PASS card_id=%s", card.card_id)
                    else:
                        logger.info(
                            "[verifier] FAIL reason=%s retry=%s",
                            result.rejection_reason,
                            result.retry_attempted,
                        )
                        if result.fallback_line:
                            fb = result.fallback_line
                            card = render_fallback_card(
                                profile_key=narration_request.profile_key,
                                moment_id=key_moment.moment_id,
                                match_clock=match_clock_dict,
                                match_seconds=match_secs,
                                language=narration_request.language,
                                card_type="key_moment",
                                priority=key_moment.priority_rank,
                                team_ref=event.team,
                                headline=fb.get("headline", ""),
                                body=fb.get("body", ""),
                                gloss_en=(
                                    GlossEn(
                                        headline=str(fb["gloss_en"].get("headline", "")),
                                        body=str(fb["gloss_en"].get("body", "")),
                                    )
                                    if narration_request.language.lower() == "sw"
                                    and isinstance(fb.get("gloss_en"), dict)
                                    else None
                                ),
                            )
                except Exception as exc:
                    logger.warning("[verifier] exception: %s", exc)

            # Narrator absent/failed or verifier returned no fallback: use the
            # deterministic fallback line directly.
            if card is None:
                fb = build_fallback_line(
                    language=narration_request.language,
                    moment_type=(
                        key_moment.trigger_tags[0]
                        if key_moment.trigger_tags
                        else "default"
                    ),
                    player=event.player,
                    minute=event.minute,
                    event_type=event.event_type.value,
                    score=f"{event.score_home}-{event.score_away}",
                )
                card = render_fallback_card(
                    profile_key=narration_request.profile_key,
                    moment_id=key_moment.moment_id,
                    match_clock=match_clock_dict,
                    match_seconds=match_secs,
                    language=narration_request.language,
                    card_type="key_moment",
                    priority=key_moment.priority_rank,
                    team_ref=event.team,
                    headline=fb.get("headline", ""),
                    body=fb.get("body", ""),
                    gloss_en=(
                        GlossEn(
                            headline=str(fb["gloss_en"].get("headline", "")),
                            body=str(fb["gloss_en"].get("body", "")),
                        )
                        if narration_request.language.lower() == "sw"
                        and isinstance(fb.get("gloss_en"), dict)
                        else None
                    ),
                )
                logger.info("[renderer] fallback card card_id=%s", card.card_id)

            # ----------------------------------------------------------
            # 8. Renderer — broadcast caption, then schedule TTS
            # ----------------------------------------------------------
            if ws_manager is not None and card is not None:
                await ws_manager.broadcast_card(
                    match_id=match_id,
                    card=_card_to_dict(card),
                    session_id=session_id,
                )
                cards_emitted += 1
                metrics.record_card_latency(
                    (time.monotonic() - _event_wall) * 1000,
                    language=language,
                    card_type=(
                        card.card_type
                        if hasattr(card, "card_type")
                        else "key_moment"
                    ),
                )
                logger.info(
                    "[ws] broadcast card #%d card_id=%s",
                    cards_emitted,
                    card.card_id,
                )

                # Audio is intentionally scheduled after the caption broadcast.
                _schedule_card_audio(
                    card=card,
                    session_id=session_id,
                    match_id=match_id,
                    language=narration_request.language,
                    match_seconds=match_secs,
                    event=event,
                    key_moment=key_moment,
                    narration_request=narration_request,
                    ws_manager=ws_manager,
                    tts_client=tts_client,
                    audio_tasks=audio_tasks,
                )

    except asyncio.CancelledError:
        logger.info(
            "[pipeline] session=%s cancelled after %d cards",
            session_id,
            cards_emitted,
        )
        await _cancel_audio_tasks(audio_tasks, session_id=session_id)
        return
    except Exception as exc:
        logger.exception("[pipeline] session=%s fatal error: %s", session_id, exc)
        # If the pipeline fails unexpectedly, avoid leaving its audio wrapper
        # tasks running without an owning session task.
        await _cancel_audio_tasks(audio_tasks, session_id=session_id)
        return

    logger.info(
        "[pipeline] session=%s complete. Total cards: %d",
        session_id,
        cards_emitted,
    )

    # ------------------------------------------------------------------
    # Emit full-time notification
    # ------------------------------------------------------------------
    if ws_manager is not None:
        await ws_manager.broadcast_clock(
            {
                "type": "full_time",
                "session_id": session_id,
                "match_id": match_id,
                "cards_emitted": cards_emitted,
            },
            match_id=match_id,
        )

    # Do not wait here for TTS: full-time delivery and pipeline completion
    # should not be delayed by synthesis. The process-level registry retains
    # background tasks until they complete; each task removes itself from both
    # registries through done callbacks. Session cancellation cancels its own
    # tasks in _cancel_audio_tasks().


__all__ = ["run_pipeline_session"]
