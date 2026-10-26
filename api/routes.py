"""REST routes for the Msimulizi API (corrections, cards, audit, and helpers).

Routes are implemented as an APIRouter so they can be mounted into the main
application factory. The implementation uses in-memory stores attached to
app.state for simple demo and unit-test convenience.
"""

from __future__ import annotations

import json
import os
import pathlib
import time
import uuid
from datetime import datetime, timezone
from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import BaseModel

from shared.content_safety import ContentSafetyClientProtocol
from shared.observability import metrics as _metrics

router = APIRouter(prefix="/v1")


class CorrectionIn(BaseModel):
    profile_key: str
    moment_id: str = ""
    match_id: str | None = None
    card_id: str | None = None
    card_type: str | None = None
    original_sw: str | None = None
    proposed_headline: str | None = None
    proposed_body: str | None = None
    note: str | None = None


def _get_client_state(request: Request) -> Any:
    return request.app.state


def _repos(state: Any) -> Any | None:
    return getattr(state, "cosmos_repos", None)


def _correction_match_id(payload: CorrectionIn) -> str:
    if payload.match_id:
        return payload.match_id
    # Profile keys are "match_id.language.mode.perspective".
    return payload.profile_key.split(".", 1)[0] or "unknown"


def _correction_view(entry: dict[str, Any]) -> dict[str, Any]:
    """Add the field names the review UI renders while preserving the store shape."""
    view = dict(entry)
    view.setdefault("card_id", entry.get("card_id", ""))
    view.setdefault("card_type", entry.get("card_type", ""))
    view.setdefault("original_sw", entry.get("original_sw", ""))
    view.setdefault(
        "suggested_sw",
        entry.get("suggested_sw")
        or entry.get("proposed_body")
        or entry.get("proposed_headline")
        or "",
    )
    view.setdefault(
        "submitted_at",
        entry.get("submitted_at")
        or datetime.fromtimestamp(
            float(entry.get("created_at", time.time())), tz=timezone.utc
        ).isoformat(),
    )
    return view


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
        "match_id": _correction_match_id(payload),
        "profile_key": payload.profile_key,
        "moment_id": payload.moment_id,
        "card_id": payload.card_id or "",
        "card_type": payload.card_type or "",
        "original_sw": payload.original_sw or "",
        "suggested_sw": payload.proposed_body or payload.proposed_headline or "",
        "proposed_headline": payload.proposed_headline,
        "proposed_body": payload.proposed_body,
        "note": payload.note,
        "status": "pending",
        "created_at": time.time(),
        "submitted_at": datetime.now(timezone.utc).isoformat(),
        "source": "api",
    }
    store[correction_id] = entry

    repos = _repos(state)
    if repos is not None and entry["match_id"] != "unknown":
        try:
            await repos.corrections.create_correction(entry)
        except Exception:
            # Keep the in-memory mirror; the reviewer can still act on it.
            pass

    return {"id": correction_id, "status": "pending"}


@router.get("/corrections/queue")
async def get_corrections_queue(request: Request, state: Any = Depends(_get_client_state), _rl=Depends(rate_limit)) -> dict[str, Any]:
    reviewer_key = os.getenv("MSIMULIZI_REVIEWER_KEY")
    header = request.headers.get("x-reviewer-key")
    if reviewer_key is None or header != reviewer_key:
        raise HTTPException(status_code=401, detail="Reviewer key required")
    store: dict = state.__dict__.setdefault("corrections_store", {})
    pending_by_id = {
        entry["id"]: entry
        for entry in store.values()
        if entry.get("status") == "pending"
    }
    repos = _repos(state)
    if repos is not None:
        try:
            for entry in await repos.corrections.list_all_corrections(status="pending"):
                pending_by_id.setdefault(entry["id"], entry)
        except Exception:
            pass
    pending = [_correction_view(entry) for entry in pending_by_id.values()]
    return {"count": len(pending), "items": pending}


@router.patch("/corrections/{correction_id}")
async def patch_correction(correction_id: str, payload: dict[str, Any], request: Request, state: Any = Depends(_get_client_state)) -> dict[str, Any]:
    # Reviewer key check
    reviewer_key = os.getenv("MSIMULIZI_REVIEWER_KEY")
    header = request.headers.get("x-reviewer-key")
    if reviewer_key is None or header != reviewer_key:
        raise HTTPException(status_code=401, detail="Reviewer key required")
    store: dict = state.__dict__.setdefault("corrections_store", {})
    patch: dict[str, Any] = {}
    status = payload.get("status")
    if status is not None:
        patch["status"] = str(status)
    editor_note = payload.get("editor_note")
    if editor_note is not None:
        patch["editor_note"] = str(editor_note)

    entry = store.get(correction_id)
    repos = _repos(state)
    if entry is None and repos is not None:
        try:
            entry = await repos.corrections.get_correction(correction_id)
        except Exception:
            entry = None
    if entry is None:
        raise HTTPException(status_code=404, detail="Correction not found")

    entry.update(patch)
    store[correction_id] = entry
    if repos is not None:
        try:
            await repos.corrections.update_correction_by_id(correction_id, patch)
        except Exception:
            pass
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
    entry = store.get(correction_id)
    repos = _repos(state)
    if entry is None and repos is not None:
        try:
            entry = await repos.corrections.get_correction(correction_id)
        except Exception:
            entry = None
    if entry is None:
        raise HTTPException(status_code=404, detail="Correction not found")

    patch = {"status": status, "reviewed_at": time.time()}
    entry.update(patch)
    store[correction_id] = entry
    if repos is not None:
        try:
            await repos.corrections.update_correction_by_id(correction_id, patch)
        except Exception:
            pass
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
    cards = list(cards_store.get(match_id, []))
    repos = _repos(state)
    if repos is not None:
        try:
            persisted = await repos.overlay_cards.list_cards(match_id)
            seen = {card.get("card_id") or card.get("id") for card in cards}
            cards.extend(
                card for card in persisted
                if (card.get("card_id") or card.get("id")) not in seen
            )
        except Exception:
            pass
    return {"match_id": match_id, "cards": cards}


@router.get("/matches/{match_id}/state")
async def get_match_state(match_id: str, request: Request, state: Any = Depends(_get_client_state), _rl=Depends(rate_limit)) -> dict[str, Any]:
    # Return the latest persisted snapshot plus active session IDs. The live
    # MCP surface is the sub-second path; this endpoint is the restart-safe
    # fallback.
    orchestrator = getattr(request.app.state, "orchestrator", None)
    sessions = (
        [s.session_id for s in orchestrator.session_store.values() if s.match_id == match_id]
        if orchestrator is not None
        else []
    )

    snapshot = None
    repos = _repos(state)
    if repos is not None:
        try:
            snapshot = await repos.match_state_snapshots.get_latest_snapshot(match_id)
        except Exception:
            snapshot = None

    if snapshot is None and not sessions:
        return {"match_id": match_id, "state": {"status": "unavailable"}}

    return {
        "match_id": match_id,
        "state": {
            "match_id": match_id,
            "sessions": sessions,
            "snapshot": snapshot,
        },
    }


@router.post("/matches/{match_id}/cards")
async def post_match_card(match_id: str, payload: dict[str, Any], request: Request, state: Any = Depends(_get_client_state)) -> dict[str, Any]:
    """Allow pushing a card into the in-memory feed (useful for integration tests)."""
    cards_store: dict = state.__dict__.setdefault("cards_store", {})
    cards_store.setdefault(match_id, []).append(payload)

    repos = _repos(state)
    if repos is not None:
        try:
            await repos.overlay_cards.upsert_dict({**payload, "match_id": match_id})
        except Exception:
            pass

    # notify websocket manager if present
    ws_mgr = getattr(state, "websocket_manager", None)
    if ws_mgr is not None:
        try:
            await ws_mgr.broadcast_card(match_id, payload)
        except Exception:
            pass
    return {"ok": True}


# Lightweight audit log endpoint used earlier in the project
@router.get("/audit/{match_id}/log")
async def get_audit_log(match_id: str, request: Request, state: Any = Depends(_get_client_state), _rl=Depends(rate_limit)) -> dict[str, Any]:
    reviewer_key = os.getenv("MSIMULIZI_REVIEWER_KEY")
    header = request.headers.get("x-reviewer-key")
    if reviewer_key is None or header != reviewer_key:
        raise HTTPException(status_code=401, detail="Reviewer key required")
    audit = state.__dict__.setdefault("audit_store", {})
    log = list(audit.get(match_id, []))
    repos = _repos(state)
    if repos is not None:
        try:
            persisted = await repos.audit_log.list_entries(match_id)
            seen = {entry.get("id") for entry in log}
            log.extend(entry for entry in persisted if entry.get("id") not in seen)
        except Exception:
            pass
    return {"match_id": match_id, "log": log}


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
    corrections_by_id = dict(corrections_store)
    repos = _repos(state)
    if repos is not None:
        try:
            for entry in await repos.corrections.list_all_corrections():
                corrections_by_id.setdefault(entry["id"], entry)
        except Exception:
            pass
    pending = [
        entry for entry in corrections_by_id.values()
        if entry.get("status") == "pending"
    ]
    corrections = [_correction_view(entry) for entry in corrections_by_id.values()]

    return {
        "latency": snap["latency"],
        "verdict_pass": snap["verdict_pass"],
        "verdict_fail": snap["verdict_fail"],
        "fallback_count": snap["fallback_count"],
        "quota_exceeded_count": snap["quota_exceeded_count"],
        "groundedness_score": groundedness_score if groundedness_score is not None else 0.0,
        "rating_queue_size": len(pending),
        "corrections": corrections,
    }
