"""Bridge between deterministic overlay cards and the production audio service.

The renderer knows nothing about speech providers. This module is the single
place that maps an ``OverlayCard`` (or a bundle card dict) onto an
``AudioRequest`` and hands it to :class:`renderer.audio.service.AudioService`.

Keeping the mapping here means the pipeline can schedule audio without
importing Azure SDKs, and the mapping is easy to test with a fake engine.
"""

from __future__ import annotations

from typing import Any, Awaitable, Callable

from .contract import AudioRequest, AudioResult
from .emotion import emotion_for_moment

__all__ = [
    "build_audio_request",
    "card_text_for_language",
    "canonical_language",
    "synthesize_card_audio",
]


_CARD_EMOTION_EVENT = {
    "goal": "goal",
    "key_moment": "big_chance",
    "player_spotlight": "big_chance",
    "recap": "momentum_swing",
    "stat": "big_chance",
}


def canonical_language(value: Any) -> str:
    """Return the project's canonical two-letter language code."""
    text = str(value or "en").strip().lower().replace("_", "-")

    if text.startswith("sw"):
        return "sw"
    if text.startswith("fr"):
        return "fr"
    return "en"


def _card_field(card: Any, name: str, default: Any = None) -> Any:
    if isinstance(card, dict):
        return card.get(name, default)
    return getattr(card, name, default)


def card_text_for_language(card: Any, language: str) -> str:
    """
    Extract speakable headline + body text for one language from a card.

    Cards normally contain only the requested language. Falling back to
    English and then the first available language keeps bundle/legacy cards
    audible instead of silently dropping audio.
    """
    text = _card_field(card, "text")

    if not isinstance(text, dict) or not text:
        return ""

    canonical = canonical_language(language)
    row = text.get(language) or text.get(canonical)

    if row is None:
        row = text.get("en")

    if row is None:
        row = next(
            (value for value in text.values() if isinstance(value, dict)),
            None,
        )

    if isinstance(row, str):
        return row.strip()

    if not isinstance(row, dict):
        return ""

    headline = str(row.get("headline") or "").strip()
    body = str(row.get("body") or "").strip()

    parts = [part for part in (headline, body) if part]
    return " ".join(parts).strip()


def build_audio_request(
    card: Any,
    *,
    language: str,
    voice_id: str,
    perspective: str = "neutral",
    late_game: bool | None = None,
    emotion_event: str | None = None,
    spoken_text: str | None = None,
    spoken_gloss_en: str | None = None,
) -> AudioRequest | None:
    """
    Build an ``AudioRequest`` from an approved card.

    ``spoken_text`` is an optional grounded rewrite used only for synthesis.
    The approved caption stays in ``source_text`` and is never replaced in the
    overlay. Passing no rewrite preserves the previous verbatim behaviour.

    Returns ``None`` when the card has no speakable text, so callers can skip
    synthesis without treating it as a failure.
    """
    source_text = card_text_for_language(card, language)

    if not source_text:
        return None

    text = (spoken_text or "").strip() or source_text

    card_type = str(_card_field(card, "card_type", "key_moment") or "key_moment")
    match_seconds = float(_card_field(card, "match_seconds", 0.0) or 0.0)
    match_minute = int(max(0.0, match_seconds) // 60)
    is_late = match_minute >= 75 if late_game is None else late_game

    event = emotion_event or _CARD_EMOTION_EVENT.get(card_type, "big_chance")
    emotion, intensity = emotion_for_moment(
        event,
        perspective,
        is_late,
    )

    return AudioRequest(
        narration_id=str(_card_field(card, "card_id", "card")),
        text=text,
        language=canonical_language(language),
        emotion=emotion,
        intensity=intensity,
        voice_id=voice_id,
        match_minute=match_minute,
        priority=int(_card_field(card, "priority", 1) or 1),
        source_text=source_text,
        gloss_en=(spoken_gloss_en or "").strip() or None,
    )


async def synthesize_card_audio(
    card: Any,
    service: Any,
    *,
    language: str,
    voice_id: str | None = None,
    publish: Callable[[dict[str, Any]], Awaitable[None] | None],
    perspective: str = "neutral",
    existing_audio_url: str | None = None,
    emotion_event: str | None = None,
    spoken_text: str | None = None,
    spoken_gloss_en: str | None = None,
) -> AudioResult | None:
    """
    Render one card's audio through an ``AudioService`` and publish the update.

    The caller should run this after broadcasting the caption so speech
    latency never delays the card. The service owns caching, retries and
    storage; this function only maps fields.

    ``voice_id`` defaults to the service's configured voice resolver, which is
    populated from ``AudioSettings`` by ``build_audio_service``. Optional
    ``spoken_text``/``spoken_gloss_en`` are a grounded audio-only rewrite; the
    card caption remains untouched.
    """
    if voice_id is None:
        resolver = getattr(service, "resolve_voice", None)

        if not callable(resolver):
            raise ValueError(
                "voice_id was omitted and the audio service has no resolver"
            )

        voice_id = resolver(language)

    request = build_audio_request(
        card,
        language=language,
        voice_id=voice_id,
        perspective=perspective,
        emotion_event=emotion_event,
        spoken_text=spoken_text,
        spoken_gloss_en=spoken_gloss_en,
    )

    if request is None:
        return None

    return await service.render_and_publish(
        request,
        card_id=request.narration_id,
        match_seconds=float(_card_field(card, "match_seconds", 0.0) or 0.0),
        publish=publish,
        existing_audio_url=existing_audio_url,
    )
