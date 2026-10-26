"""REST routes for the Msimulizi API (corrections, cards, audit, and helpers).

Routes are implemented as an APIRouter mounted by the application factory.
In-memory stores remain intended for the current demo and unit tests.

The manual card-ingestion route optionally schedules audio after broadcasting
its card. The main live pipeline schedules audio in api.pipeline_runner; this
route is for directly posted/test cards and should not be called a second time
for the same card by the pipeline.
"""

from __future__ import annotations

import asyncio
import json
import logging
import os
import pathlib
import time
import uuid
from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import BaseModel

from shared.content_safety import ContentSafetyClientProtocol
from shared.observability import metrics as _metrics

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/v1")


class CorrectionIn(BaseModel):
    profile_key: str
    moment_id: str
    proposed_headline: str | None = None
    proposed_body: str | None = None
    note: str | None = None


def _get_client_state(request: Request) -> Any:
    return request.app.state


# Simple per-IP rate limiter dependency
async def rate_limit(request: Request, state: Any = Depends(_get_client_state)) -> None:
    ip = request.client.host if request.client else "127.0.0.1"
    bucket = state.__dict__.setdefault("ip_buckets", {})
    now = time.time()
    window = 60.0
    limit = int(os.getenv("MSIMULIZI_PER_IP_RATE_LIMIT", "120"))
    entry = bucket.get(ip)
    if entry is None or now > entry[1]:
        bucket[ip] = [1, now + window]
        return
    if entry[0] >= limit:
        raise HTTPException(status_code=429, detail="Too many requests from this IP")
    entry[0] += 1


def _language_for_card(card: dict[str, Any]) -> str:
    """Resolve language from explicit card metadata, then available text keys."""
    raw = card.get("language")
    if isinstance(raw, str) and raw.strip():
        value = raw.strip().lower().replace("_", "-")
        if value.startswith("sw"):
            return "sw"
        if value.startswith("fr"):
            return "fr"
        if value.startswith("en"):
            return "en"

    text = card.get("text")
    if isinstance(text, dict):
        for candidate in text:
            value = str(candidate).strip().lower().replace("_", "-")
            if value.startswith("sw"):
                return "sw"
            if value.startswith("fr"):
                return "fr"
            if value.startswith("en"):
                return "en"

    return "en"


def _has_speakable_card_text(card: dict[str, Any], language: str) -> bool:
    """Return True only when the card has real headline/body text to speak."""
    text = card.get("text")
    if isinstance(text, dict):
        row = (
            text.get(language)
            or text.get("en")
            or next(iter(text.values()), None)
        )
        if isinstance(row, dict):
            if str(row.get("headline") or "").strip() or str(row.get("body") or "").strip():
                return True

    # Compatibility with simple legacy cards that have top-level text fields.
    if str(card.get("headline") or "").strip() or str(card.get("body") or "").strip():
        return True

    return False


def _match_seconds_for_card(card: dict[str, Any]) -> float:
    """Read match_seconds or derive it from minute/second fields."""
    raw = card.get("match_seconds")
    if isinstance(raw, (int, float)) and not isinstance(raw, bool):
        return float(raw)

    try:
        minute = int(card.get("minute", card.get("match_minute", 0)) or 0)
    except (TypeError, ValueError):
        minute = 0
    try:
        second = int(card.get("second", 0) or 0)
    except (TypeError, ValueError):
        second = 0

    return float(max(0, minute) * 60 + max(0, min(second, 59)))


def _schedule_manual_card_audio(
    *,
    state: Any,
    card: dict[str, Any],
    match_id: str,
    session_id: str | None,
    profile_key: str | None,
    language: str,
    match_seconds: float,
    websocket_manager: Any,
) -> None:
    """Schedule audio for a manually posted card without blocking the route."""
    # The application lifespan registers this facade alongside the shared
    # AudioService. If audio is disabled, cards still work normally.
    tts_client = getattr(state, "speech_client", None)
    audio_service = getattr(state, "audio_service", None)
    if tts_client is None or audio_service is None:
        return

    publish_method = getattr(websocket_manager, "broadcast_audio_update", None)
    if not callable(publish_method):
        logger.warning(
            "[routes.audio] WebSocket manager lacks broadcast_audio_update; "
            "skipping TTS publication for card %s",
            card.get("card_id"),
        )
        return

    # Avoid scheduling TTS for malformed/test cards with no actual narration.
    if not _has_speakable_card_text(card, language):
        logger.debug(
            "[routes.audio] no speakable text for card %s; skipping TTS",
            card.get("card_id"),
        )
        return

    async def publish_audio_update(audio_payload: dict[str, Any]) -> None:
        # Send the exact four-field top-level audio_update. Do not use
        # broadcast_clock(), which wraps events in clock_update.clock.
        await websocket_manager.broadcast_audio_update(
            audio_payload,
            session_id=session_id,
            match_id=match_id,
            profile_key=profile_key,
        )

    async def render() -> None:
        try:
            from renderer.tts import synthesize_card_audio

            # Keep canonical routing/context on the copied card. Do not mutate
            # a caller-owned payload after it has been saved/broadcast.
            audio_card = dict(card)
            audio_card["language"] = language
            audio_card["match_seconds"] = match_seconds

            # Normalize locale-style keys (for example ``sw-KE``) to the
            # canonical short key expected by renderer.tts._extract_text_for_language.
            text_map = audio_card.get("text")
            if isinstance(text_map, dict):
                for text_language, row in text_map.items():
                    normalized = str(text_language).strip().lower().replace("_", "-")
                    normalized = normalized.split("-", maxsplit=1)[0]
                    if normalized == language and isinstance(row, dict):
                        normalized_map = dict(text_map)
                        normalized_map[language] = row
                        audio_card["text"] = normalized_map
                        break

            await synthesize_card_audio(
                audio_card,
                synthesizer=tts_client,
                language=language,
                publisher=publish_audio_update,
            )
        except asyncio.CancelledError:
            raise
        except Exception:
            # Audio is optional; never turn a successful card post into failure.
            logger.exception(
                "[routes.audio] background synthesis failed for card %s",
                card.get("card_id"),
            )

    tasks: set[asyncio.Task[Any]] = state.__dict__.setdefault(
        "route_audio_tasks", set()
    )
    task = asyncio.create_task(
        render(),
        name=f"route-audio-{match_id}-{card.get('card_id', 'unknown')}",
    )
    tasks.add(task)
    task.add_done_callback(tasks.discard)


@router.post("/corrections")
async def submit_correction(payload: CorrectionIn, request: Request, state: Any = Depends(_get_client_state), _rl=Depends(rate_limit)) -> dict[str, Any]:
    """Submit a user correction to be reviewed.

    Runs a content-safety check when a client is attached to the app state.
    """
    store: dict = state.__dict__.setdefault("corrections_store", {})
    correction_id = str(uuid.uuid4())
    text = (payload.proposed_body or "") + "\n" + (payload.proposed_headline or "")

    # Optionally run content safety if configured
    cs_client: ContentSafetyClientProtocol | None = getattr(state, "content_safety", None)
    if cs_client is not None:
        try:
            result = await cs_client.check(text, context="correction")
            if hasattr(result, "__class__") and result.__class__.__name__ == "Blocked":
                return {"id": correction_id, "status": "rejected", "reason": "content_blocked"}
        except Exception:
            # on safety API failure, keep the correction as pending for manual review
            pass

    entry = {
        "id": correction_id,
        "profile_key": payload.profile_key,
        "moment_id": payload.moment_id,
        "proposed_headline": payload.proposed_headline,
        "proposed_body": payload.proposed_body,
        "note": payload.note,
        "status": "pending",
        "created_at": time.time(),
    }
    store[correction_id] = entry
    return {"id": correction_id, "status": "pending"}


@router.get("/corrections/queue")
async def get_corrections_queue(request: Request, state: Any = Depends(_get_client_state), _rl=Depends(rate_limit)) -> dict[str, Any]:
    reviewer_key = os.getenv("MSIMULIZI_REVIEWER_KEY")
    header = request.headers.get("x-reviewer-key")
    if reviewer_key is None or header != reviewer_key:
        raise HTTPException(status_code=401, detail="Reviewer key required")
    store: dict = state.__dict__.setdefault("corrections_store", {})
    pending = [v for v in store.values() if v.get("status") == "pending"]
    return {"count": len(pending), "items": pending}


@router.patch("/corrections/{correction_id}")
async def patch_correction(correction_id: str, payload: dict[str, Any], request: Request, state: Any = Depends(_get_client_state)) -> dict[str, Any]:
    # Reviewer key check
    reviewer_key = os.getenv("MSIMULIZI_REVIEWER_KEY")
    header = request.headers.get("x-reviewer-key")
    if reviewer_key is None or header != reviewer_key:
        raise HTTPException(status_code=401, detail="Reviewer key required")
    store: dict = state.__dict__.setdefault("corrections_store", {})
    if correction_id not in store:
        raise HTTPException(status_code=404, detail="Correction not found")
    entry = store[correction_id]
    # allow status and notes updates
    status = payload.get("status")
    if status is not None:
        entry["status"] = str(status)
    editor_note = payload.get("editor_note")
    if editor_note is not None:
        entry["editor_note"] = str(editor_note)
    store[correction_id] = entry
    return entry


async def _set_correction_status(
    correction_id: str,
    status: str,
    request: Request,
    state: Any,
) -> dict[str, Any]:
    reviewer_key = os.getenv("MSIMULIZI_REVIEWER_KEY")
    header = request.headers.get("x-reviewer-key") or request.headers.get("x-api-key")
    if reviewer_key is None or header != reviewer_key:
        raise HTTPException(status_code=401, detail="Reviewer key required")
    store: dict = state.__dict__.setdefault("corrections_store", {})
    if correction_id not in store:
        raise HTTPException(status_code=404, detail="Correction not found")
    entry = store[correction_id]
    entry["status"] = status
    entry["reviewed_at"] = time.time()
    store[correction_id] = entry
    return entry


@router.post("/corrections/{correction_id}/approve")
async def approve_correction(
    correction_id: str,
    request: Request,
    state: Any = Depends(_get_client_state),
) -> dict[str, Any]:
    return await _set_correction_status(correction_id, "approved", request, state)


@router.post("/corrections/{correction_id}/reject")
async def reject_correction(
    correction_id: str,
    request: Request,
    state: Any = Depends(_get_client_state),
) -> dict[str, Any]:
    return await _set_correction_status(correction_id, "rejected", request, state)


@router.get("/matches/{match_id}/cards")
async def get_match_cards(match_id: str, request: Request, state: Any = Depends(_get_client_state), _rl=Depends(rate_limit)) -> dict[str, Any]:
    cards_store: dict = state.__dict__.setdefault("cards_store", {})
    return {"match_id": match_id, "cards": cards_store.get(match_id, [])}


@router.get("/matches/{match_id}/state")
async def get_match_state(match_id: str, request: Request, state: Any = Depends(_get_client_state), _rl=Depends(rate_limit)) -> dict[str, Any]:
    # Return a lightweight state snapshot from the orchestrator when available
    orchestrator = getattr(request.app.state, "orchestrator", None)
    if orchestrator is None:
        return {"match_id": match_id, "state": {"status": "unavailable"}}
    # Try to find a session for the match
    sessions = [s for s in orchestrator.session_store.values() if s.match_id == match_id]
    return {"match_id": match_id, "state": {"match_id": match_id, "sessions": [s.session_id for s in sessions]}}


@router.post("/matches/{match_id}/cards")
async def post_match_card(match_id: str, payload: dict[str, Any], request: Request, state: Any = Depends(_get_client_state)) -> dict[str, Any]:
    """Push a card to the in-memory feed and optionally synthesize its audio.

    Captions/cards are stored and broadcast immediately. If the shared audio
    service is configured and this payload contains narration text, audio is
    scheduled in a background task. This route is intended for manual posting
    and integration tests; cards generated by api.pipeline_runner already have
    their own audio scheduling path.
    """
    cards_store: dict = state.__dict__.setdefault("cards_store", {})

    # Copy to avoid mutating the request parser's payload object indirectly.
    card = dict(payload)
    cards_store.setdefault(match_id, []).append(card)

    ws_mgr = getattr(state, "websocket_manager", None)
    session_id = card.get("session_id")
    profile_key = card.get("profile_key")

    if ws_mgr is not None:
        try:
            await ws_mgr.broadcast_card(
                match_id,
                card,
                session_id=str(session_id) if session_id else None,
                profile_key=str(profile_key) if profile_key else None,
            )
        except Exception:
            logger.exception("Could not broadcast manually posted card for match %s", match_id)

        # Need an explicit card_id to correlate an asynchronous audio_update with
        # the card displayed by the frontend. Do not invent a new identifier if
        # the client has not supplied one: skip TTS and retain the card as-is.
        card_id = card.get("card_id")
        language = _language_for_card(card)
        if card_id and _has_speakable_card_text(card, language):
            _schedule_manual_card_audio(
                state=state,
                card=card,
                match_id=match_id,
                session_id=str(session_id) if session_id else None,
                profile_key=str(profile_key) if profile_key else None,
                language=language,
                match_seconds=_match_seconds_for_card(card),
                websocket_manager=ws_mgr,
            )
        elif not card_id:
            logger.debug(
                "[routes.audio] manually posted card has no card_id; TTS skipped"
            )

    return {"ok": True}


# Lightweight audit log endpoint used earlier in the project
@router.get("/audit/{match_id}/log")
async def get_audit_log(match_id: str, request: Request, state: Any = Depends(_get_client_state), _rl=Depends(rate_limit)) -> dict[str, Any]:
    reviewer_key = os.getenv("MSIMULIZI_REVIEWER_KEY")
    header = request.headers.get("x-reviewer-key")
    if reviewer_key is None or header != reviewer_key:
        raise HTTPException(status_code=401, detail="Reviewer key required")
    audit = state.__dict__.setdefault("audit_store", {})
    return {"match_id": match_id, "log": audit.get(match_id, [])}


def _load_groundedness_result() -> float | None:
    """Read the latest groundedness score from the eval results file, if present."""
    results_path = pathlib.Path("evals/results/groundedness_latest.json")
    if not results_path.exists():
        return None
    try:
        data = json.loads(results_path.read_text(encoding="utf-8"))
        score = data.get("groundedness_score")
        if isinstance(score, (int, float)):
            return float(score)
    except Exception:
        pass
    return None


@router.get("/review")
async def get_review_dashboard(request: Request, state: Any = Depends(_get_client_state)) -> dict[str, Any]:
    """Return observability metrics for the /review dashboard (reviewer key required)."""
    reviewer_key = os.getenv("MSIMULIZI_REVIEWER_KEY")
    header = request.headers.get("x-reviewer-key") or request.headers.get("x-api-key")
    if reviewer_key is not None and header != reviewer_key:
        raise HTTPException(status_code=401, detail="Reviewer key required")

    snap = _metrics.snapshot()

    groundedness_score = _load_groundedness_result()
    corrections_store: dict = state.__dict__.setdefault("corrections_store", {})
    pending = [v for v in corrections_store.values() if v.get("status") == "pending"]

    return {
        "latency": snap["latency"],
        "verdict_pass": snap["verdict_pass"],
        "verdict_fail": snap["verdict_fail"],
        "fallback_count": snap["fallback_count"],
        "quota_exceeded_count": snap["quota_exceeded_count"],
        "groundedness_score": groundedness_score if groundedness_score is not None else 0.0,
        "rating_queue_size": len(pending),
        "corrections": list(corrections_store.values()),
    }
