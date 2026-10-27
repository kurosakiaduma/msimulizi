"""
Grounded spoken-script enhancement for Msimulizi audio.

The overlay caption is approved and never changes. This module asks Foundry for
a short, natural commentary line derived from that caption, with a strict
no-new-facts contract. The result is used only for speech synthesis; the
caption shown to the viewer remains the original approved card.

The enhancer is deliberately fail-open: any timeout, quota error, malformed
response, or unsafe rewrite returns ``None`` so the caller can synthesize the
approved caption verbatim.
"""

from __future__ import annotations

import asyncio
import json
import logging
import re

from dataclasses import dataclass
from typing import Any

from .bridge import canonical_language, card_text_for_language


logger = logging.getLogger("msimulizi.audio.script")


_MAX_CHARS = 240
_MAX_WORDS = 34
_MAX_SENTENCES = 3
_MAX_GLOSS_CHARS = 320

_NUMBER_RE = re.compile(r"\b\d+(?:[.,]\d+)?\b")
_SCORE_RE = re.compile(r"\b(\d+)\s*[-–—:]\s*(\d+)\b")
_SENTENCE_RE = re.compile(r"[.!?]+")
_BANNED_PHRASES = (
    "as an ai",
    "caption",
    "card text",
    "here is",
    "sound effect",
    "stage direction",
    "spoken line",
    "translation",
    "gloss:",
)

_SCHEMA: dict[str, Any] = {
    "type": "object",
    "additionalProperties": False,
    "properties": {
        "spoken_text": {
            "type": "string",
            "maxLength": _MAX_CHARS,
            "description": "One or two short spoken sentences in the target language.",
        },
        "gloss_en": {
            "type": "string",
            "maxLength": _MAX_GLOSS_CHARS,
            "description": "Faithful English gloss of the spoken Swahili line.",
        },
    },
    "required": ["spoken_text", "gloss_en"],
}

_LANGUAGE_NAMES = {
    "sw": "Swahili",
    "en": "English",
    "fr": "French",
}

_COMMENTARY_BEATS = {
    "goal": (
        "a reaction, then one consequence supported by score_state: a lead, "
        "an equaliser, a comeback, or the new scoreline"
    ),
    "red_card": "a reaction, then the numerical disadvantage",
    "big_chance": (
        "a reaction, then that this chance was missed or close, and the "
        "unchanged score if useful"
    ),
    "momentum_swing": "a reaction, then the shift in momentum",
    "stat": "a reaction, then the supplied stat without interpreting it",
}


@dataclass(frozen=True)
class SpokenScript:
    """A grounded spoken rewrite and its English gloss."""

    text: str
    gloss_en: str


def _field(card: Any, name: str, default: Any = None) -> Any:
    if isinstance(card, dict):
        return card.get(name, default)
    return getattr(card, name, default)


def _text_row(card: Any, language: str) -> dict[str, str]:
    text = _field(card, "text")
    if not isinstance(text, dict) or not text:
        return {"headline": "", "body": ""}

    canonical = canonical_language(language)
    row = text.get(language) or text.get(canonical) or text.get("en")
    if row is None:
        row = next(
            (value for value in text.values() if isinstance(value, dict)),
            None,
        )

    if isinstance(row, str):
        return {"headline": "", "body": row.strip()}

    if not isinstance(row, dict):
        return {"headline": "", "body": ""}

    return {
        "headline": str(row.get("headline") or "").strip(),
        "body": str(row.get("body") or "").strip(),
    }


def _gloss_row(card: Any) -> dict[str, str]:
    gloss = _field(card, "gloss_en")
    if gloss is None:
        return {"headline": "", "body": ""}
    if isinstance(gloss, dict):
        return {
            "headline": str(gloss.get("headline") or "").strip(),
            "body": str(gloss.get("body") or "").strip(),
        }
    return {
        "headline": str(getattr(gloss, "headline", "") or "").strip(),
        "body": str(getattr(gloss, "body", "") or "").strip(),
    }


def _score_state(score_home: int | None, score_away: int | None) -> str:
    if score_home is None or score_away is None:
        return ""
    if score_home > score_away:
        return "home_lead"
    if score_away > score_home:
        return "away_lead"
    return "level"


def _clean(text: Any) -> str:
    return " ".join(str(text or "").split()).strip()


def _normalise(text: str) -> str:
    return " ".join(re.sub(r"[^\w\s]", " ", text.casefold()).split())


def _rejection_reason(
    *,
    text: str,
    gloss: str,
    source_text: str,
    language: str,
    score: str,
    minute: int | None,
) -> str:
    if not text:
        return "empty spoken text"
    if len(text) > _MAX_CHARS:
        return "spoken text is too long"

    words = text.split()
    if len(words) < 4:
        return "spoken text is too short"
    if len(words) > _MAX_WORDS:
        return "spoken text has too many words"
    if len(_SENTENCE_RE.findall(text)) > _MAX_SENTENCES:
        return "spoken text has too many sentences"

    if any(quote in text for quote in ('"', "“", "”")):
        return "spoken text contains quotation marks"

    lowered = text.casefold()
    for phrase in _BANNED_PHRASES:
        if phrase in lowered:
            return f"spoken text contains meta phrase {phrase!r}"

    if _normalise(text) == _normalise(source_text):
        return "spoken text is the caption verbatim"

    if language == "sw" and len(gloss) < 3:
        return "Swahili spoken text has no English gloss"
    if gloss and len(gloss) > _MAX_GLOSS_CHARS:
        return "English gloss is too long"

    allowed_numbers = set(
        _NUMBER_RE.findall(
            " ".join(
                part
                for part in (
                    source_text,
                    score,
                    str(minute) if minute is not None else "",
                )
                if part
            )
        )
    )
    for number in _NUMBER_RE.findall(text):
        if number not in allowed_numbers:
            return f"spoken text adds number {number!r}"

    allowed_scores = {
        (match.group(1), match.group(2))
        for match in _SCORE_RE.finditer(f"{source_text} {score}")
    }
    for match in _SCORE_RE.finditer(text):
        if (match.group(1), match.group(2)) not in allowed_scores:
            return f"spoken text changes the score to {match.group(0)!r}"

    if not any(character.isalpha() for character in text):
        return "spoken text has no letters"

    return ""


class SpokenScriptEnhancer:
    """
    Turn an approved card into a short spoken line without changing the card.

    ``client`` only needs an async ``structured_output(agent_key, messages,
    schema)`` method. That keeps the enhancer testable with a tiny fake and
    independent of Azure SDKs.
    """

    def __init__(
        self,
        client: Any,
        *,
        timeout_s: float = 8.0,
        max_concurrency: int = 2,
    ) -> None:
        if client is None:
            raise ValueError("SpokenScriptEnhancer needs a structured-output client")
        if timeout_s <= 0:
            raise ValueError("timeout_s must be greater than zero")
        if max_concurrency < 1:
            raise ValueError("max_concurrency must be at least 1")

        self._client = client
        self._timeout_s = float(timeout_s)
        self._sem = asyncio.Semaphore(max_concurrency)

    async def enhance(
        self,
        *,
        card: Any,
        language: str,
        perspective: str = "neutral",
        event: str = "momentum_swing",
        score_home: int | None = None,
        score_away: int | None = None,
        minute: int | None = None,
    ) -> SpokenScript | None:
        """
        Return a grounded spoken rewrite, or ``None`` to use the caption.

        The caller must treat ``None`` as a normal fallback, not an error.
        """
        source_text = card_text_for_language(card, language)
        if not source_text:
            return None

        lang = canonical_language(language)
        row = _text_row(card, language)
        gloss_row = _gloss_row(card)
        if minute is None:
            try:
                minute = int(
                    max(0.0, float(_field(card, "match_seconds", 0.0) or 0.0))
                    // 60
                )
            except (TypeError, ValueError):
                minute = None

        score = (
            f"{score_home}-{score_away}"
            if score_home is not None and score_away is not None
            else ""
        )
        context = {
            "language": lang,
            "language_name": _LANGUAGE_NAMES.get(lang, "English"),
            "event": event,
            "perspective": perspective,
            "card_type": str(_field(card, "card_type", "key_moment") or "key_moment"),
            "minute": minute,
            "score": score,
            "score_state": _score_state(score_home, score_away),
            "commentary_beat": _COMMENTARY_BEATS.get(
                event,
                _COMMENTARY_BEATS["momentum_swing"],
            ),
            "headline": row["headline"],
            "body": row["body"],
            "gloss_headline": gloss_row["headline"],
            "gloss_body": gloss_row["body"],
            "approved_caption": source_text,
        }

        messages = [
            {
                "role": "system",
                "content": (
                    "You are the spoken-commentary adapter for Msimulizi, a "
                    "synthetic football highlight show. An approved caption "
                    "already exists and must not be changed. Turn it into live "
                    "commentary for a TTS commentator: not a caption read "
                    "aloud, and not a compressed copy of the caption.\n\n"
                    "Hard rules:\n"
                    "- Use only facts in the supplied JSON. Never invent a "
                    "player, team, score, minute, injury, tactical claim, or "
                    "outcome.\n"
                    "- Do not add a new player or team name. Refer to people "
                    "and teams only as they appear in the caption, or use a "
                    "pronoun such as 'wanaongoza'.\n"
                    "- Keep the scoreline and minute exactly if you use them. "
                    "Use score_state to choose between a lead, an equaliser, "
                    "and a comeback; never change the score.\n"
                    "- Include the commentary beat named in commentary_beat. "
                    "Start with a natural reaction supported by the event, "
                    "then add one short consequence or momentum phrase. The "
                    "output must contain a clear commentary beat beyond the "
                    "caption.\n"
                    "- Do not add sustained pressure, tactical dominance, "
                    "predictions, or claims about how the match will "
                    "continue. For a big chance, do not say a team keeps "
                    "pressing or is dominating; describe only this chance. "
                    "For a stat, do not explain causes or trends.\n"
                    "- 1-2 sentences, at most 32 words. No stage directions, "
                    "labels, emojis, quotation marks, markdown, or "
                    "meta-commentary.\n"
                    "- Write in the requested language. For Swahili, return a "
                    "faithful English gloss in gloss_en. For English or "
                    "French, gloss_en may be an English gloss or an empty "
                    "string.\n\n"
                    "Shape examples, not text to copy (replace placeholders "
                    "with the caption's facts):\n"
                    "- Swahili goal + away_lead: 'Goli! [player]! "
                    "Wanaongoza kwa [score] sasa.'\n"
                    "- Swahili goal + level: 'Goli! [player]! "
                    "Wamesawazisha kuwa [score].'\n"
                    "- Swahili red card: 'Kadi nyekundu! Sasa wanacheza na "
                    "wachezaji wachache.'\n"
                    "- Swahili big chance: 'Nafasi kubwa! [player] apiga "
                    "juu! Bado ni [score].'\n"
                    "- English goal + home_lead: 'Goal! [player]! They lead "
                    "[score] now.'\n"
                    "- French goal + level: 'But! [player] ! Ils égalisent "
                    "[score].'"
                ),
            },
            {
                "role": "user",
                "content": (
                    "Write the spoken line from this approved caption JSON. "
                    "Return only the structured object.\n"
                    + json.dumps(context, ensure_ascii=False)
                ),
            },
        ]

        agent_key = "spoken_script_sw" if lang == "sw" else "spoken_script_en_fr"

        try:
            async with self._sem:
                result = await asyncio.wait_for(
                    self._client.structured_output(
                        agent_key,
                        messages,
                        _SCHEMA,
                        timeout_s=self._timeout_s,
                    ),
                    timeout=self._timeout_s + 0.5,
                )
        except asyncio.TimeoutError:
            logger.info("[audio-script] fallback: Foundry timed out")
            return None
        except Exception as exc:
            logger.info(
                "[audio-script] fallback: Foundry unavailable (%s)",
                type(exc).__name__,
            )
            return None

        if not isinstance(result, dict):
            logger.info("[audio-script] fallback: response was not an object")
            return None

        text = _clean(result.get("spoken_text"))
        gloss = _clean(result.get("gloss_en"))
        reason = _rejection_reason(
            text=text,
            gloss=gloss,
            source_text=source_text,
            language=lang,
            score=score,
            minute=minute,
        )
        if reason:
            logger.info("[audio-script] fallback: %s", reason)
            return None

        logger.info(
            "[audio-script] enhanced language=%s card=%s chars=%d",
            lang,
            str(_field(card, "card_id", "?")),
            len(text),
        )
        return SpokenScript(text=text, gloss_en=gloss)


__all__ = ["SpokenScript", "SpokenScriptEnhancer"]
