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
from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import BaseModel

from shared.content_safety import ContentSafetyClientProtocol
from shared.observability import metrics as _metrics

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
    """Allow pushing a card into the in-memory feed (useful for integration tests)."""
    cards_store: dict = state.__dict__.setdefault("cards_store", {})
    cards_store.setdefault(match_id, []).append(payload)
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
