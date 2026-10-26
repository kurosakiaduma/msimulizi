"""api/pipeline_runner.py — asyncio pipeline driver for a single replay session.

This module contains the event loop that drives one match from the adapter through
every pipeline stage and pushes resulting OverlayCards to the WebSocket gateway.

It is intentionally separate from orchestrator.py, which holds the Agent-Framework
workflow declaration. This file owns the per-session asyncio task and the
stage-by-stage wiring.

Design notes
------------
* One coroutine per session; spawned as an asyncio.Task from api/main.py.
* Every stage runs sequentially inside the loop. LLM stages (Explainer, Narrator,
  Verifier) are awaited; deterministic stages are synchronous calls.
* Failure recovery follows the spec: Verifier fail → Narrator retry → Fallback Line.
* A QuotaExceeded error falls back to template narration and logs the event.
* Clock updates are broadcast after every event so the browser clock tracks
  match time in real time.
"""

from __future__ import annotations

import asyncio
import dataclasses
import logging
import os
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
from shared.foundry_client import QuotaExceeded
from shared.models import EventType, GlossEn, KeyMoment, MatchState, OverlayCard
from shared.observability import metrics

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _match_clock(state: MatchState) -> dict[str, int]:
    return {"period": state.sequence_number and 1 or 1, "minute": state.minute, "second": state.second}


def _match_seconds(state: MatchState) -> float:
    return float(state.minute * 60 + state.second)


def _card_to_dict(card: OverlayCard) -> dict[str, Any]:
    """Convert an OverlayCard dataclass to a JSON-serialisable dict."""
    d = dataclasses.asdict(card)
    # StructuredExplanation and GlossEn are nested dataclasses — asdict handles them.
    return d


async def _render_card_audio(
    *,
    card: Any,
    audio_service: Any,
    language: str,
    ws_manager: Any,
    match_id: str,
    session_id: str,
    existing_audio_url: str | None = None,
) -> None:
    """Synthesize one card's audio and broadcast ``audio_update``.

    Runs after the caption has already been sent, so a slow speech call never
    delays the viewer. Failures are contained inside ``AudioService`` and
    produce ``audio_url=null`` instead of breaking the pipeline.
    """
    from renderer.audio.bridge import synthesize_card_audio

    started = time.monotonic()

    async def publish(payload: dict[str, Any]) -> None:
        await ws_manager.broadcast_message(
            payload,
            match_id=match_id,
            session_id=session_id,
        )

    try:
        await synthesize_card_audio(
            card,
            audio_service,
            language=language,
            publish=publish,
            existing_audio_url=existing_audio_url,
        )
    except Exception as exc:  # pragma: no cover - service already contains most
        logger.warning("[audio] card %s failed: %s", getattr(card, "card_id", "?"), exc)
    else:
        metrics.record_audio_latency((time.monotonic() - started) * 1000.0)


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
    audio_service: Any | None = None,
    tts_client: Any | None = None,
    content_safety: Any | None = None,
    narration_cache: dict[str, Any] | None = None,
    bundle_cards: dict[str, Any] | None = None,
) -> None:
    """Drive a synthetic match session through the full pipeline.

    Parameters
    ----------
    session_id:
        The caller-assigned session identifier (used for WebSocket routing).
    match_id:
        Stable match identifier for this storyline + seed combination.
    storyline:
        Storyline name passed to the generator / adapter.
    seed:
        Random seed for the generator (deterministic replay).
    speed:
        Replay speed multiplier (1.0 = real-time, 4.0 = 4× faster).
    language:
        Preferred narration language for the default profile.
    mode:
        Narration mode — ``"casual"`` or ``"analyst"``.
    ws_manager:
        The WebSocketManager instance for broadcasting cards.
    foundry_client:
        A FoundryClient (or MockFoundryClient) for LLM calls.
    audio_service:
        Optional production AudioService (renderer.audio). Audio is rendered
        in the background after each caption and published as audio_update.
    tts_client:
        Backwards-compatible alias for ``audio_service``.
    content_safety:
        An optional ContentSafetyClient; skipped when absent.
    narration_cache:
        Optional in-memory dict seeded from the bundle; cache hits skip the LLM.
    bundle_cards:
        Optional pre-generated cards by profile_key; used when quota is exceeded.
    """
    if audio_service is None:
        audio_service = tts_client

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
    audio_tasks: set[asyncio.Task[Any]] = set()
    recent_events: list[Any] = []
    # Use one epoch anchor for the whole replay so the browser can derive the
    # same continuously advancing match clock between event notifications.
    clock_anchor_wall = time.time() * 1000.0
    clock_anchor_match = 0.0

    try:
        async for event in adapter.events(session_id, speed=speed):
            # Record wall time at event receipt for end-to-end latency measurement.
            _event_wall = time.monotonic()

            # ----------------------------------------------------------
            # 1. Interpreter — update rolling match state
            # ----------------------------------------------------------
            state: MatchState = await asyncio.to_thread(interpreter.process_event, event)

            # ----------------------------------------------------------
            # 2. Broadcast clock update + event dot so the browser tracks
            #    match time and the pitch shows event locations
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
                # rolling state for momentum / possession / xG display
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
                await ws_manager.broadcast_clock(
                    clock_payload,
                    match_id=match_id,
                )
                # Also broadcast a raw event dot for the pitch visualiser
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

            # track recent events for spotlight assist detection
            recent_events.append(event)
            if len(recent_events) > 200:
                recent_events = recent_events[-200:]

            if key_moment is None:
                # No moment: emit a lightweight score/event update
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
                key_moment.moment_id, key_moment.trigger_tags,
                key_moment.priority_rank, key_moment.minute,
            )

            # ----------------------------------------------------------
            # 4. Personaliser — build NarrationRequest
            # ----------------------------------------------------------
            narration_request = personaliser.prepare(key_moment, event=event, match_id=match_id)
            if narration_request is None:
                # Cache hit — card already sent for this profile key
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
                    explanation.theme, not explanation.partially_grounded,
                )
            except Exception as exc:  # pragma: no cover
                logger.warning("[explainer] failed: %s", exc)
                explanation = None

            # ----------------------------------------------------------
            # 6. Narrator — generate narration
            # ----------------------------------------------------------
            narrator_response = None
            _quota_exceeded = False
            card: OverlayCard | None = None

            # Check in-memory narration cache first (populated from bundle at startup)
            _cache_key = f"{narration_request.profile_key}:{narration_request.moment_id}"
            _match_seconds = float(event.minute * 60 + event.second)
            _card_type = "goal" if "goal" in key_moment.trigger_tags else "key_moment"
            cached = narration_cache.get(_cache_key) if narration_cache is not None else None
            if cached is None:
                cached = _find_bundle_card(
                    bundle_cards,
                    profile_key=narration_request.profile_key,
                    match_seconds=_match_seconds,
                    card_type=_card_type,
                )
            if cached is not None:
                logger.info("[narrator] cache hit for %s", _cache_key)
                # Treat the cached dict as already verified — skip to rendering
                card_type = _card_type
                match_clock_dict = {"period": event.period, "minute": event.minute, "second": event.second}
                match_secs = _match_seconds
                from shared.models import GlossEn as _GlossEn
                # Build a minimal card from the cached dict
                text = cached.get("text") or {"en": {"headline": cached.get("headline", ""), "body": cached.get("body", "")}}
                gloss_raw = cached.get("gloss_en")
                gloss_en = _GlossEn(headline=gloss_raw["headline"], body=gloss_raw["body"]) if isinstance(gloss_raw, dict) else None
                from renderer.renderer import render_narration_card as _rnc
                from shared.models import NarratorResponse as _NR
                _nr = _NR(
                    profile_key=narration_request.profile_key,
                    moment_id=narration_request.moment_id,
                    headline=text.get("en", {}).get("headline", "") or text.get(narration_request.language, {}).get("headline", ""),
                    body=text.get("en", {}).get("body", "") or text.get(narration_request.language, {}).get("body", ""),
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
                    evidence_event_ids=(explanation.evidence_event_ids if explanation else []),
                )
                card.from_bundle = cached.get("from_bundle", False)
                cached_audio_url = cached.get("audio_url")
                if isinstance(cached_audio_url, str) and cached_audio_url:
                    card.audio_url = cached_audio_url
                # Skip to broadcast
            else:
                try:
                    narrator_response = await narrator.generate(narration_request)
                    logger.info("[narrator] headline=%r", narrator_response.headline[:50])
                except QuotaExceeded:
                    logger.warning("[narrator] QuotaExceeded — trying bundle fallback")
                    metrics.record_quota_exceeded()
                    _quota_exceeded = True
                except Exception as exc:
                    logger.warning("[narrator] failed: %s", exc)

            # ----------------------------------------------------------
            # 7. Verifier — validate + emit card
            # ----------------------------------------------------------
            if card is None:  # may have been set via cache hit above
                match_clock_dict = {"period": event.period, "minute": event.minute, "second": event.second}
                match_secs = float(event.minute * 60 + event.second)

                # Quota exceeded — try the bundle first, then Fallback Line
                if _quota_exceeded and bundle_cards is not None:
                    from scripts.generate_bundle import serve_bundle_card_for_quota_exceeded
                    bundle_hit = serve_bundle_card_for_quota_exceeded(
                        narration_request.profile_key,
                        key_moment.moment_id,
                        bundle_cards,
                    )
                    if bundle_hit is not None:
                        logger.info("[narrator] serving bundle card on QuotaExceeded")
                        # Convert the bundle dict back to an OverlayCard-compatible dict for broadcast
                        card = None  # will fall through to build a fallback card below
                        # Broadcast the bundle card directly as a dict
                        bundle_hit["from_bundle"] = True
                        if ws_manager is not None:
                            await ws_manager.broadcast_card(
                                match_id=match_id,
                                card=bundle_hit,
                                session_id=session_id,
                            )
                            cards_emitted += 1
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
                        card_type = "goal" if "goal" in key_moment.trigger_tags else "key_moment"
                        card = render_narration_card(
                            response=result.response,
                            match_clock=match_clock_dict,
                            match_seconds=match_secs,
                            card_type=card_type,
                            priority=key_moment.priority_rank,
                            team_ref=event.team,
                            player_ref=event.player if event.player else None,
                            structured_explanation=explanation,
                            evidence_event_ids=(explanation.evidence_event_ids if explanation else []),
                        )
                        logger.info("[verifier] PASS card_id=%s", card.card_id)
                    else:
                        logger.info(
                            "[verifier] FAIL reason=%s retry=%s",
                            result.rejection_reason, result.retry_attempted,
                        )
                        # Use the fallback line from the verifier if present
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

            # Narrator absent or failed — use fallback line directly
            if card is None:
                fb = build_fallback_line(
                    language=narration_request.language,
                    moment_type=(key_moment.trigger_tags[0] if key_moment.trigger_tags else "default"),
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
            # 8. Renderer — broadcast card to WebSocket clients
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
                    card_type=card.card_type if hasattr(card, "card_type") else "key_moment",
                )
                logger.info("[ws] broadcast card #%d card_id=%s", cards_emitted, card.card_id)

                # Speech runs after the caption. Bundle cards already carry a
                # pre-generated URL, so only synthesize when audio is missing.
                if audio_service is not None and not card.audio_url:
                    task = asyncio.create_task(
                        _render_card_audio(
                            card=card,
                            audio_service=audio_service,
                            language=language,
                            ws_manager=ws_manager,
                            match_id=match_id,
                            session_id=session_id,
                        ),
                        name=f"audio-{card.card_id}",
                    )
                    audio_tasks.add(task)
                    task.add_done_callback(audio_tasks.discard)

    except asyncio.CancelledError:
        for task in list(audio_tasks):
            task.cancel()
        logger.info("[pipeline] session=%s cancelled after %d cards", session_id, cards_emitted)
        return
    except Exception as exc:
        for task in list(audio_tasks):
            task.cancel()
        logger.exception("[pipeline] session=%s fatal error: %s", session_id, exc)
        return

    # Let in-flight speech finish before the session is reported complete.
    # The cap prevents a stuck provider from holding the session open.
    if audio_tasks:
        pending = list(audio_tasks)
        _, still_running = await asyncio.wait(pending, timeout=15.0)
        for task in still_running:
            task.cancel()
        if still_running:
            logger.warning(
                "[audio] session=%s cancelled %d audio task(s) after timeout",
                session_id,
                len(still_running),
            )

    logger.info("[pipeline] session=%s complete. Total cards: %d", session_id, cards_emitted)

    # ------------------------------------------------------------------
    # Emit full-time notification
    # ------------------------------------------------------------------
    if ws_manager is not None:
        await ws_manager.broadcast_clock(
            {"type": "full_time", "session_id": session_id, "match_id": match_id, "cards_emitted": cards_emitted},
            match_id=match_id,
        )


__all__ = ["run_pipeline_session"]
