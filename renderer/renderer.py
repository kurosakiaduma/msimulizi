"""Deterministic overlay rendering for approved narration and template cards.

The renderer sits at the boundary between the narrative pipeline and the
viewer-facing OverlayCard stream. It turns a verified NarratorResponse (or a
local template fallback) into the canonical ``OverlayCard`` format the rest of
Msimulizi consumes.
"""

from __future__ import annotations

import asyncio
import hashlib
import inspect
from datetime import datetime
from pathlib import Path
from typing import Any

import yaml

from shared.models import GlossEn, NarratorResponse, OverlayCard

_CARD_DURATION_MS = {
    "goal": 8000,
    "key_moment": 6000,
    "stat": 4000,
    "player_spotlight": 5000,
    "recap": 10000,
}

_ROOT = Path(__file__).resolve().parent


def _safe_trim(value: Any, default: str = "") -> str:
    if value is None:
        return default
    return str(value).strip()


def _load_yaml(path: Path) -> dict[str, Any]:
    try:
        with path.open("r", encoding="utf-8") as handle:
            loaded = yaml.safe_load(handle) or {}
    except OSError:
        return {}
    return loaded if isinstance(loaded, dict) else {}


def build_card_id(
    *,
    card_type: str,
    profile_key: str,
    moment_id: str | None = None,
    period: int | None = None,
    minute: int | None = None,
    player: str | None = None,
    event_id: str | None = None,
) -> str:
    """Build a stable card identifier from the relevant rendering key.

    The rules follow the task specification exactly:
    - LLM cards: profile_key + moment_id
    - stat cards: profile_key + period + minute
    - spotlight cards: profile_key + player + event_id
    """
    card_type = (card_type or "key_moment").lower()
    payload: str
    if card_type in {"goal", "key_moment", "recap"}:
        payload = f"{profile_key}|{moment_id or 'moment'}"
    elif card_type == "stat":
        payload = f"{profile_key}|{period if period is not None else 0}|{minute if minute is not None else 0}"
    elif card_type == "player_spotlight":
        payload = f"{profile_key}|{_safe_trim(player, 'player')}|{event_id or 'event'}"
    else:
        payload = f"{profile_key}|{card_type}"
    digest = hashlib.sha256(payload.encode("utf-8")).hexdigest()[:16]
    return f"card-{card_type}-{digest}"


def _match_id_from_profile_key(profile_key: str) -> str:
    return profile_key.split(".", 1)[0] if profile_key else "match"


def _from_response(response: NarratorResponse, *, language: str) -> dict[str, dict[str, str]]:
    language = (language or "en").lower()
    text: dict[str, dict[str, str]] = {}
    if response.headline:
        text[language] = {"headline": response.headline, "body": response.body}
    else:
        text[language] = {"headline": "Match update", "body": response.body}
    return text


def _ensure_text_block(block: dict[str, Any] | None, *, default_headline: str, default_body: str) -> dict[str, str]:
    if not isinstance(block, dict):
        return {"headline": default_headline, "body": default_body}
    headline = _safe_trim(block.get("headline"), default_headline)
    body = _safe_trim(block.get("body"), default_body)
    return {"headline": headline, "body": body}


def render_narration_card(
    *,
    response: NarratorResponse,
    match_clock: dict[str, int],
    match_seconds: float,
    card_type: str = "key_moment",
    priority: int = 1,
    team_ref: str = "team",
    player_ref: str | None = None,
    structured_explanation: Any = None,
    evidence_event_ids: list[str] | None = None,
    stat_payload: dict[str, Any] | None = None,
) -> OverlayCard:
    """Render a verified narration response into an ``OverlayCard``."""
    profile_key = response.profile_key
    card_id = build_card_id(
        card_type=card_type,
        profile_key=profile_key,
        moment_id=response.moment_id,
    )

    text_by_language: dict[str, dict[str, str]] = {}
    for language in ("en", "fr", "sw"):
        if language == "sw":
            headline = response.headline if response.headline else "Mabadiliko ya mechi"
            body = response.body if response.body else "Mchezo unaendelea."
            gloss = response.gloss_en
            if gloss is not None:
                text_by_language[language] = {"headline": headline, "body": body}
            else:
                text_by_language[language] = {"headline": headline, "body": body}
        else:
            text_by_language[language] = {
                "headline": response.headline if response.headline else "Match update",
                "body": response.body if response.body else "The action continues.",
            }

    if "sw" not in text_by_language:
        text_by_language["sw"] = text_by_language.get("en", {"headline": response.headline, "body": response.body})

    card = OverlayCard(
        card_id=card_id,
        match_id=_match_id_from_profile_key(profile_key),
        profile_key=profile_key,
        match_clock=dict(match_clock),
        match_seconds=float(match_seconds),
        display_duration_ms=_CARD_DURATION_MS.get(card_type, 6000),
        card_type=card_type,
        priority=priority,
        player_ref=player_ref,
        team_ref=team_ref,
        text=text_by_language,
        gloss_en=response.gloss_en,
        structured_explanation=structured_explanation,
        evidence_event_ids=evidence_event_ids or [],
        stat_payload=stat_payload or {},
        audio_url=None,
        synthetic_ai_generated=True,
        from_bundle=False,
    )
    return card


def render_fallback_card(
    *,
    profile_key: str,
    moment_id: str,
    match_clock: dict[str, int],
    match_seconds: float,
    language: str,
    card_type: str = "key_moment",
    priority: int = 1,
    team_ref: str = "team",
    player_ref: str | None = None,
    headline: str | None = None,
    body: str | None = None,
    gloss_en: GlossEn | None = None,
    stat_payload: dict[str, Any] | None = None,
) -> OverlayCard:
    """Render a locally generated fallback line into an ``OverlayCard``."""
    text_by_language: dict[str, dict[str, str]] = {}
    language = (language or "en").lower()
    base_headline = _safe_trim(headline, "Match update")
    base_body = _safe_trim(body, "The action continues.")
    for lang in ("en", "fr", "sw"):
        if lang == "sw":
            text_by_language[lang] = {"headline": base_headline if language == "sw" else base_headline, "body": base_body if language == "sw" else base_body}
        else:
            text_by_language[lang] = {"headline": base_headline, "body": base_body}
    card = OverlayCard(
        card_id=build_card_id(card_type=card_type, profile_key=profile_key, moment_id=moment_id),
        match_id=_match_id_from_profile_key(profile_key),
        profile_key=profile_key,
        match_clock=dict(match_clock),
        match_seconds=float(match_seconds),
        display_duration_ms=_CARD_DURATION_MS.get(card_type, 6000),
        card_type=card_type,
        priority=priority,
        player_ref=player_ref,
        team_ref=team_ref,
        text=text_by_language,
        gloss_en=gloss_en,
        structured_explanation=None,
        evidence_event_ids=[],
        stat_payload=stat_payload or {},
        audio_url=None,
        synthetic_ai_generated=False,
        from_bundle=False,
    )
    return card


def _load_template_file(name: str) -> dict[str, Any]:
    return _load_yaml(_ROOT / name)


def render_stat_card(
    *,
    profile_key: str,
    period: int,
    minute: int,
    language: str = "en",
    stat_label: str = "Possession",
    stat_value: str = "50%",
    team_ref: str = "team",
    match_id: str | None = None,
    match_seconds: float | None = None,
) -> OverlayCard:
    """Render a stat card from the local YAML templates."""
    templates = _load_template_file("stat_templates.yaml")
    template = templates.get("default", {})
    block = template.get((language or "en").lower(), template.get("en", {}))
    headline = str(block.get("headline", "Stat update")).format(stat_label=stat_label, stat_value=stat_value)
    body = str(block.get("body", "The latest stat is {stat_value}.")).format(stat_label=stat_label, stat_value=stat_value)
    card_id = build_card_id(card_type="stat", profile_key=profile_key, period=period, minute=minute)
    match_clock = {"period": period, "minute": minute, "second": 0}
    return OverlayCard(
        card_id=card_id,
        match_id=match_id or _match_id_from_profile_key(profile_key),
        profile_key=profile_key,
        match_clock=match_clock,
        match_seconds=float(match_seconds or (period * 45 * 60) + minute * 60),
        display_duration_ms=_CARD_DURATION_MS["stat"],
        card_type="stat",
        priority=3,
        player_ref=None,
        team_ref=team_ref,
        text={
            "en": {"headline": headline, "body": body},
            "fr": {"headline": headline, "body": body},
            "sw": {"headline": headline, "body": body},
        },
        gloss_en=None,
        structured_explanation=None,
        evidence_event_ids=[],
        stat_payload={"label": stat_label, "value": stat_value},
        audio_url=None,
        synthetic_ai_generated=False,
        from_bundle=False,
    )


def render_spotlight_card(
    *,
    profile_key: str,
    player: str,
    team_ref: str,
    event_id: str,
    language: str = "en",
    headline: str | None = None,
    body: str | None = None,
    match_clock: dict[str, int] | None = None,
    match_seconds: float | None = None,
) -> OverlayCard:
    """Render a spotlight card from local templates or supplied text."""
    templates = _load_template_file("spotlight_templates.yaml")
    template = templates.get("default", {})
    block = template.get((language or "en").lower(), template.get("en", {}))
    resolved_headline = _safe_trim(headline, str(block.get("headline", "Spotlight")).format(player=player))
    resolved_body = _safe_trim(body, str(block.get("body", "Focus on {player}." )).format(player=player))
    clock = match_clock or {"period": 1, "minute": 0, "second": 0}
    card = OverlayCard(
        card_id=build_card_id(card_type="player_spotlight", profile_key=profile_key, player=player, event_id=event_id),
        match_id=_match_id_from_profile_key(profile_key),
        profile_key=profile_key,
        match_clock=dict(clock),
        match_seconds=float(match_seconds or 0.0),
        display_duration_ms=_CARD_DURATION_MS["player_spotlight"],
        card_type="player_spotlight",
        priority=2,
        player_ref=player,
        team_ref=team_ref,
        text={
            "en": {"headline": resolved_headline, "body": resolved_body},
            "fr": {"headline": resolved_headline, "body": resolved_body},
            "sw": {"headline": resolved_headline, "body": resolved_body},
        },
        gloss_en=None,
        structured_explanation=None,
        evidence_event_ids=[event_id],
        stat_payload={},
        audio_url=None,
        synthetic_ai_generated=False,
        from_bundle=False,
    )
    return card


class OverlayRenderer:
    """Thin convenience wrapper around the deterministic card builders."""

    def __init__(self, *, bus: Any | None = None, cosmos_repo: Any | None = None, tts_runner: Any | None = None):
        self.bus = bus
        self.cosmos_repo = cosmos_repo
        self.tts_runner = tts_runner

    async def publish(self, card: OverlayCard) -> OverlayCard:
        if self.cosmos_repo is not None and hasattr(self.cosmos_repo, "upsert_card"):
            await self.cosmos_repo.upsert_card(card)
        if self.bus is not None and hasattr(self.bus, "publish"):
            await self.bus.publish("overlay_cards", {"type": "card", "card": card})
        if self.tts_runner is not None:
            try:
                if hasattr(self.tts_runner, "__call__"):
                    tts_result = self.tts_runner(card=card)
                    if inspect.isawaitable(tts_result):
                        asyncio.ensure_future(tts_result)
            except Exception:
                pass
        return card

    async def render_response(self, response: NarratorResponse, *, match_clock: dict[str, int], match_seconds: float, **kwargs: Any) -> OverlayCard:
        card = render_narration_card(response=response, match_clock=match_clock, match_seconds=match_seconds, **kwargs)
        return await self.publish(card)

    async def render_stat(self, *, profile_key: str, period: int, minute: int, **kwargs: Any) -> OverlayCard:
        card = render_stat_card(profile_key=profile_key, period=period, minute=minute, **kwargs)
        return await self.publish(card)

    async def render_spotlight(self, *, profile_key: str, player: str, team_ref: str, event_id: str, **kwargs: Any) -> OverlayCard:
        card = render_spotlight_card(profile_key=profile_key, player=player, team_ref=team_ref, event_id=event_id, **kwargs)
        return await self.publish(card)


__all__ = [
    "OverlayRenderer",
    "build_card_id",
    "render_fallback_card",
    "render_narration_card",
    "render_spotlight_card",
    "render_stat_card",
]
