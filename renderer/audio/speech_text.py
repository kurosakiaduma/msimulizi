
"""
Speech-text preparation for Msimulizi.

This module transforms approved narration into speech-friendly text.
It must not modify the caption shown to the viewer.

Responsibilities:
- Normalize supported language codes.
- Reduce exaggerated repeated letters in speech text.
- Verbalize football scorelines for Swahili, English, and French.
- Preserve the rest of the narration, including expressive punctuation.

Keep this module independent of Azure and the speech engine so that all
engines receive the same normalized text.
"""

from __future__ import annotations

import re

from .contract import Language


# Increment whenever prepare_tts_text changes in a way that can alter audio.
# This version is included in the audio cache key.
TTS_TEXT_VERSION = "t2"


# Examples:
#   2-1      -> scoreline
#   2 - 1    -> scoreline
#   45-55%   -> unchanged percentage range
#
# The percentage guard prevents a common false match. If your narration
# includes other numeric ranges, consider marking scorelines explicitly in
# the upstream narration structure instead of guessing from punctuation.
_SCORE_RE = re.compile(r"\b(\d+)\s*-\s*(\d+)\b(?!\s*%)")

# Reduce three or more repeated ASCII letters to two:
#   GOOOOLI -> GOOLI
#   waaah   -> waah
#
# This only affects text sent to speech synthesis; the visual caption remains
# untouched.
_STRETCH_RE = re.compile(r"([A-Za-z])\1{2,}")

# Collapse repeated horizontal whitespace without removing intentional
# line breaks that may be used to structure the narration.
_HORIZONTAL_SPACE_RE = re.compile(r"[ \t\f\v]+")


def _canonical_language(language: str | Language | None) -> str:
    """
    Normalize short language codes and locale-style identifiers.

    Examples:
        sw       -> sw
        sw-KE    -> sw
        en-GB    -> en
        fr-FR    -> fr
    """
    value = str(language or "en").strip().lower().replace("_", "-")

    if value.startswith("sw"):
        return "sw"

    if value.startswith("en"):
        return "en"

    if value.startswith("fr"):
        return "fr"

    return value


def prepare_tts_text(text: str, language: str | Language) -> str:
    """
    Prepare approved narration for TTS.

    Supported transformations:
      1. Trim leading/trailing whitespace.
      2. Collapse repeated horizontal whitespace.
      3. Reduce exaggerated repeated letters.
      4. Verbalize common scoreline formats.

    The function does not translate text, rewrite commentary, add facts,
    remove punctuation, or modify the original caption.

    Args:
        text: Approved narration to synthesize.
        language: Canonical language code or locale, for example "sw" or
                  "sw-KE".

    Returns:
        Speech-friendly text.

    Raises:
        TypeError: If text is not a string.
    """
    if not isinstance(text, str):
        raise TypeError(
            f"text must be str, got {type(text).__name__}"
        )

    lang = _canonical_language(language)

    cleaned = text.strip()
    if not cleaned:
        return ""

    cleaned = _HORIZONTAL_SPACE_RE.sub(" ", cleaned)
    cleaned = _STRETCH_RE.sub(r"\1\1", cleaned)

    def verbalize_score(match: re.Match[str]) -> str:
        home_score, away_score = match.group(1), match.group(2)

        if lang == "sw":
            # Example: 2-1 -> 2 kwa 1
            return f"{home_score} kwa {away_score}"

        if lang == "fr":
            # Example: 2-1 -> 2 à 1
            return f"{home_score} à {away_score}"

        if lang == "en":
            # Football-style English score pronunciation.
            if home_score == away_score:
                if home_score == "0":
                    return "nil nil"
                return f"{home_score} all"

            if away_score == "0":
                return f"{home_score} nil"

            if home_score == "0":
                return f"nil {away_score}"

            # Example: 2-1 -> 2 1
            # The configured English voice supplies number pronunciation.
            return f"{home_score} {away_score}"

        # Unknown language: do not impose another language's score convention.
        return match.group(0)

    return _SCORE_RE.sub(verbalize_score, cleaned)


__all__ = [
    "TTS_TEXT_VERSION",
    "prepare_tts_text",
]

