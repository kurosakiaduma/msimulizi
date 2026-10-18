"""Deterministic fallback narration templates for verifier failures.

The Fallback Line is intentionally template-based and must not depend on any LLM
or on the broadcaster's event stream beyond player, minute, event type, and
score. This keeps the system resilient when a narration generation or verifier
pass fails.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

import yaml

from shared.models import Claim, GlossEn, NarratorResponse

_ROOT = Path(__file__).resolve().parent
_TEMPLATE_PATH = _ROOT / "fallback_templates.yaml"


def _load_templates() -> dict[str, Any]:
    """Load the fallback templates from YAML or return a minimal built-in fallback."""
    try:
        with _TEMPLATE_PATH.open("r", encoding="utf-8") as handle:
            loaded = yaml.safe_load(handle) or {}
    except OSError:
        loaded = {}
    if not isinstance(loaded, dict):
        return {}
    return loaded


def _as_text(value: Any, *, default: str = "") -> str:
    """Convert a value to trimmed text for template rendering."""
    if value is None:
        return default
    return str(value).strip()


def _render_template(template: str, **context: Any) -> str:
    """Simple string placeholder replacement for fallback template text."""
    rendered = template
    for key, value in context.items():
        rendered = rendered.replace("{" + key + "}", _as_text(value))
    return rendered


def build_fallback_line(
    *,
    language: str = "en",
    moment_type: str = "default",
    player: str | None = None,
    minute: int | None = None,
    event_type: str | None = None,
    score: str | None = None,
) -> dict[str, Any]:
    """Return a fallback narration line for the requested language and moment type."""
    templates = _load_templates()
    default_templates = templates.get("default", {})
    moment_templates = default_templates.get(moment_type, default_templates.get("default", {}))
    selected = moment_templates.get(language.lower(), moment_templates.get("en", {}))
    if not isinstance(selected, dict):
        selected = {"headline": "Match update", "body": "The action continues at {minute}."}

    player_name = _as_text(player, default="Team")
    minute_text = str(minute) if minute is not None else "0"
    score_text = _as_text(score, default="0-0")
    headline = _render_template(
        str(selected.get("headline", "Match update")),
        player=player_name,
        minute=minute_text,
        event_type=_as_text(event_type, default="event"),
        score=score_text,
    )
    body = _render_template(
        str(selected.get("body", "The action continues.")),
        player=player_name,
        minute=minute_text,
        event_type=_as_text(event_type, default="event"),
        score=score_text,
    )
    result: dict[str, Any] = {"headline": headline, "body": body}

    gloss = selected.get("gloss_en")
    if isinstance(gloss, dict):
        result["gloss_en"] = {
            "headline": _render_template(
                str(gloss.get("headline", "Match update")),
                player=player_name,
                minute=minute_text,
                event_type=_as_text(event_type, default="event"),
                score=score_text,
            ),
            "body": _render_template(
                str(gloss.get("body", "The action continues.")),
                player=player_name,
                minute=minute_text,
                event_type=_as_text(event_type, default="event"),
                score=score_text,
            ),
        }
    if language.lower() == "sw" and "gloss_en" not in result:
        result["gloss_en"] = {
            "headline": "Match update",
            "body": "The action continues as the score stands at " + score_text + ".",
        }
    return result


def make_fallback_line(*, language: str = "en", moment_type: str = "default", **kwargs: Any) -> dict[str, Any]:
    """Compatibility alias for callers using the shorter function name."""
    return build_fallback_line(language=language, moment_type=moment_type, **kwargs)


def fallback_response(
    *,
    profile_key: str,
    moment_id: str,
    language: str = "en",
    moment_type: str = "default",
    player: str | None = None,
    minute: int | None = None,
    score: str | None = None,
) -> NarratorResponse:
    """Return a ``NarratorResponse`` instance for a fallback narration line."""
    line = build_fallback_line(
        language=language,
        moment_type=moment_type,
        player=player,
        minute=minute,
        score=score,
    )
    claims: list[Claim] = []
    if player is not None:
        claims.append(Claim(claim_type="player", value=player))
    if minute is not None:
        claims.append(Claim(claim_type="minute", value=str(minute)))
    if score is not None:
        claims.append(Claim(claim_type="score", value=score))
    gloss = line.get("gloss_en")
    gloss_en = None
    if isinstance(gloss, dict):
        gloss_en = GlossEn(headline=str(gloss.get("headline", "")), body=str(gloss.get("body", "")))
    return NarratorResponse(
        profile_key=profile_key,
        moment_id=moment_id,
        headline=str(line["headline"]),
        body=str(line["body"]),
        claims_list=claims,
        gloss_en=gloss_en,
    )


__all__ = [
    "build_fallback_line",
    "make_fallback_line",
    "fallback_response",
    "_load_templates",
]
