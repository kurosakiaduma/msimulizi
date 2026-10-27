"""REST routes for the Msimulizi API (corrections, cards, audit, and helpers).

Routes are implemented as an APIRouter so they can be mounted into the main
application factory. The implementation uses in-memory stores attached to
app.state for simple demo and unit-test convenience.
"""

from __future__ import annotations

import hashlib
import json
import os
import pathlib
import time
import uuid
from datetime import datetime, timezone
from functools import lru_cache
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


class SwahiliReviewIn(BaseModel):
    """One native-speaker review of a generated Swahili card."""

    id: str
    card_id: str = ""
    match_id: str = ""
    headline: str
    body: str = ""
    gloss_headline: str = ""
    gloss_body: str = ""
    fluency: int
    idiom: int
    faithfulness: int
    note: str = ""
    corrected_headline: str = ""
    corrected_body: str = ""
    reviewer: str
    blocking: bool = False


def _get_client_state(request: Request) -> Any:
    return request.app.state


def _require_reviewer(request: Request) -> None:
    """Reviewer routes accept either the reviewer key or the API key."""
    reviewer_key = os.getenv("MSIMULIZI_REVIEWER_KEY")
    header = request.headers.get("x-reviewer-key") or request.headers.get("x-api-key")
    if reviewer_key is None or header != reviewer_key:
        raise HTTPException(status_code=401, detail="Reviewer key required")


@lru_cache(maxsize=1)
def _swahili_review_seed() -> tuple[dict[str, Any], ...]:
    """Load the unique Swahili bundle lines that need a human review.

    The bundle is static and local, so the read is cached for the process.
    Lines are deduplicated by their Swahili text because the same card appears
    for several profiles. A line without an English gloss is not reviewable:
    the rubric requires the gloss for the reviewer and for the product.
    """
    root = pathlib.Path(__file__).resolve().parents[1]
    narrations = root / "bundle" / "narrations"
    if not narrations.exists():
        return ()

    items: dict[str, dict[str, Any]] = {}
    for path in sorted(narrations.glob("*.sw.*.json")):
        try:
            cards = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            continue
        if not isinstance(cards, list):
            continue

        for card in cards:
            if not isinstance(card, dict):
                continue
            text = card.get("text") or {}
            sw = text.get("sw") if isinstance(text, dict) else None
            gloss = card.get("gloss_en")
            if not isinstance(sw, dict) or not isinstance(gloss, dict):
                continue

            headline = str(sw.get("headline") or "").strip()
            body = str(sw.get("body") or "").strip()
            gloss_headline = str(gloss.get("headline") or "").strip()
            gloss_body = str(gloss.get("body") or "").strip()
            if not headline or not gloss_headline:
                continue

            item_id = "sw-" + hashlib.sha1(
                f"{headline}\n{body}".encode("utf-8")
            ).hexdigest()[:16]
            if item_id in items:
                continue

            clock = card.get("match_clock") if isinstance(card.get("match_clock"), dict) else {}
            items[item_id] = {
                "id": item_id,
                "card_id": str(card.get("card_id") or ""),
                "match_id": str(card.get("match_id") or ""),
                "minute": int(clock.get("minute") or 0),
                "headline": headline,
                "body": body,
                "gloss_headline": gloss_headline,
                "gloss_body": gloss_body,
                "source": "bundle",
            }

    # The few-shot corpus is also part of the review evidence: it is text the
    # narrator is conditioned on. Existing ratings in the JSONL are not treated
    # as this reviewer's sign-off; the line still enters the queue as pending.
    few_shots = root / "config" / "few_shots" / "sw.jsonl"
    if few_shots.exists():
        for line in few_shots.read_text(encoding="utf-8").splitlines():
            try:
                record = json.loads(line)
            except json.JSONDecodeError:
                continue
            if not isinstance(record, dict):
                continue
            output = record.get("output") if isinstance(record.get("output"), dict) else {}
            inp = record.get("input") if isinstance(record.get("input"), dict) else {}
            gloss = output.get("gloss_en") if isinstance(output.get("gloss_en"), dict) else {}
            headline = str(output.get("headline") or "").strip()
            body = str(output.get("body") or "").strip()
            gloss_headline = str(gloss.get("headline") or "").strip()
            gloss_body = str(gloss.get("body") or "").strip()
            if not headline or not gloss_headline:
                continue
            item_id = "sw-" + hashlib.sha1(
                f"{headline}\n{body}".encode("utf-8")
            ).hexdigest()[:16]
            if item_id in items:
                continue
            items[item_id] = {
                "id": item_id,
                "card_id": "",
                "match_id": "",
                "minute": int(inp.get("minute") or 0),
                "headline": headline,
                "body": body,
                "gloss_headline": gloss_headline,
                "gloss_body": gloss_body,
                "source": "few_shot",
            }

    return tuple(items.values())


def _native_review_view(entry: dict[str, Any]) -> dict[str, Any]:
    """Shape a stored native review for the dashboard."""
    scores = entry.get("scores") if isinstance(entry.get("scores"), dict) else {}
    return {
        "id": entry.get("id"),
        "reviewer": entry.get("reviewer", ""),
        "fluency": int(scores.get("fluency", 0) or 0),
        "idiom": int(scores.get("idiom", 0) or 0),
        "faithfulness": int(scores.get("faithfulness", 0) or 0),
        "note": entry.get("note", ""),
        "corrected_headline": entry.get("corrected_headline", ""),
        "corrected_body": entry.get("corrected_body", ""),
        "blocking": bool(entry.get("blocking", False)),
        "requires_second_review": bool(entry.get("requires_second_review", False)),
        "submitted_at": entry.get("submitted_at", ""),
    }


async def _swahili_review_payload(state: Any) -> dict[str, Any]:
    """Merge the static queue with persisted reviews and compute the summary."""
    stored_by_item: dict[str, dict[str, Any]] = {}
    store: dict = state.__dict__.setdefault("corrections_store", {})
    for entry in store.values():
        if entry.get("source") == "native_review" and entry.get("review_item_id"):
            stored_by_item[str(entry["review_item_id"])] = entry

    repos = _repos(state)
    if repos is not None:
        try:
            for entry in await repos.corrections.list_all_corrections():
                if entry.get("source") == "native_review" and entry.get("review_item_id"):
                    stored_by_item.setdefault(str(entry["review_item_id"]), entry)
        except Exception:
            pass

    items: list[dict[str, Any]] = []
    for seed in _swahili_review_seed():
        item = dict(seed)
        entry = stored_by_item.get(seed["id"])
        item["review"] = _native_review_view(entry) if entry else None
        items.append(item)

    # Put unreviewed lines first so the reviewer sees the remaining work.
    items.sort(key=lambda item: (item["review"] is not None, item["minute"], item["id"]))

    scores: list[float] = []
    for entry in stored_by_item.values():
        values = entry.get("scores") if isinstance(entry.get("scores"), dict) else {}
        numeric = [
            float(values.get(key, 0) or 0)
            for key in ("fluency", "idiom", "faithfulness")
        ]
        if all(1 <= value <= 5 for value in numeric):
            scores.append(sum(numeric) / 3)

    return {
        "items": items,
        "count": len(items),
        "reviewed": len(stored_by_item),
        "average": round(sum(scores) / len(scores), 2) if scores else None,
        "sign_off_required": len(stored_by_item) < 30,
    }


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


@router.get("/review/swahili")
async def get_swahili_review_queue(
    request: Request,
    state: Any = Depends(_get_client_state),
) -> dict[str, Any]:
    """Return the native-speaker queue and the current signed-off summary."""
    _require_reviewer(request)
    return await _swahili_review_payload(state)


@router.post("/review/swahili")
async def submit_swahili_review(
    payload: SwahiliReviewIn,
    request: Request,
    state: Any = Depends(_get_client_state),
) -> dict[str, Any]:
    """Record one reviewer's scores for a generated Swahili line."""
    _require_reviewer(request)

    if not payload.reviewer.strip():
        raise HTTPException(status_code=422, detail="Reviewer name is required")
    for label, value in (
        ("fluency", payload.fluency),
        ("idiom", payload.idiom),
        ("faithfulness", payload.faithfulness),
    ):
        if value < 1 or value > 5:
            raise HTTPException(
                status_code=422,
                detail=f"{label} must be between 1 and 5",
            )
    if not payload.headline.strip() or not payload.gloss_headline.strip():
        raise HTTPException(
            status_code=422,
            detail="Swahili headline and English gloss are required",
        )

    corrected = bool(
        payload.corrected_headline.strip() or payload.corrected_body.strip()
    )
    review_id = str(uuid.uuid4())
    now = datetime.now(timezone.utc)
    entry: dict[str, Any] = {
        "id": review_id,
        "match_id": payload.match_id or "review",
        "profile_key": "native-review",
        "card_id": payload.card_id,
        "card_type": "swahili_review",
        "original_sw": f"{payload.headline}\n{payload.body}".strip(),
        "suggested_sw": (
            f"{payload.corrected_headline}\n{payload.corrected_body}".strip()
            if corrected
            else ""
        ),
        "status": "reviewed",
        "source": "native_review",
        "review_item_id": payload.id,
        "reviewer": payload.reviewer.strip(),
        "scores": {
            "fluency": payload.fluency,
            "idiom": payload.idiom,
            "faithfulness": payload.faithfulness,
        },
        "note": payload.note.strip(),
        "corrected_headline": payload.corrected_headline.strip(),
        "corrected_body": payload.corrected_body.strip(),
        "blocking": bool(payload.blocking),
        # The rubric requires an independent second reviewer for any edit.
        "requires_second_review": corrected,
        "created_at": time.time(),
        "submitted_at": now.isoformat(),
        "reviewed_at": time.time(),
    }

    store: dict = state.__dict__.setdefault("corrections_store", {})
    store[review_id] = entry

    repos = _repos(state)
    if repos is not None:
        try:
            await repos.corrections.create_correction(entry)
        except Exception:
            # The in-memory mirror keeps the review usable for this session.
            pass

    return {
        "id": review_id,
        "status": "reviewed",
        "review_item_id": payload.id,
        "requires_second_review": corrected,
    }


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
    swahili_review = await _swahili_review_payload(state)

    return {
        "latency": snap["latency"],
        "verdict_pass": snap["verdict_pass"],
        "verdict_fail": snap["verdict_fail"],
        "fallback_count": snap["fallback_count"],
        "quota_exceeded_count": snap["quota_exceeded_count"],
        "groundedness_score": groundedness_score,
        "rating_queue_size": len(pending),
        "corrections": corrections,
        "swahili_review": swahili_review,
    }
