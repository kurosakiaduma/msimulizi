
"""
Deterministic emotion and prosody policy for Msimulizi.

Responsibilities:
1. Map a verified event and viewer perspective to emotion and intensity.
2. Convert emotion and intensity into baseline prosody offsets.
3. Select optional Azure speaking styles only when the voice advertises them.

Emotion selection is independent of the TTS provider.

Examples:
- A favourable goal can sound excited.
- An unfavourable goal can sound disappointed.
- A dangerous attack can create anticipation or tension.

These mappings are policy defaults. Tune them using native-language listening
tests, especially for Swahili football commentary.
"""

from __future__ import annotations

import math
from dataclasses import dataclass

from .contract import Emotion


# Increment whenever emotion or prosody policy changes in a way that may alter
# generated audio. This version contributes to the cache key.
PROSODY_VERSION = "p2"


# ===========================================================================
# Utilities
# ===========================================================================

def clamp01(value: float) -> float:
    """
    Clamp a numeric value to [0.0, 1.0].

    Non-finite values are treated as 0.0 to avoid propagating NaN or infinity
    into SSML or engine-specific controls.
    """
    try:
        number = float(value)
    except (TypeError, ValueError):
        return 0.0

    if not math.isfinite(number):
        return 0.0

    return max(0.0, min(1.0, number))


# ===========================================================================
# 1. Event and perspective -> emotion
# ===========================================================================

# Keys use the Moment Agent's event vocabulary.
#
# Perspective is relative to the viewer's club:
#   favourable    the event benefits the viewer's club
#   unfavourable  the event harms the viewer's club
#   neutral       commentary without a team-specific emotional stance
#
# Keep the mapping deterministic. It should be driven by verified match
# facts and viewer preferences, not a free-form LLM emotion prediction.

_EMOTION_TABLE: dict[
    tuple[str, str],
    tuple[Emotion, float],
] = {
    ("goal", "favourable"): ("excitement", 0.85),
    ("goal", "unfavourable"): ("disappointment", 0.70),
    ("goal", "neutral"): ("excitement", 0.75),

    ("equaliser", "favourable"): ("relief", 0.90),
    ("equaliser", "unfavourable"): ("shock", 0.80),
    ("equaliser", "neutral"): ("excitement", 0.85),

    ("red_card", "favourable"): ("anticipation", 0.60),
    ("red_card", "unfavourable"): ("shock", 0.75),
    ("red_card", "neutral"): ("tension", 0.70),

    ("big_chance", "favourable"): ("anticipation", 0.75),
    ("big_chance", "unfavourable"): ("tension", 0.75),
    ("big_chance", "neutral"): ("anticipation", 0.65),

    ("momentum_swing", "favourable"): ("anticipation", 0.50),
    ("momentum_swing", "unfavourable"): ("tension", 0.60),
    ("momentum_swing", "neutral"): ("tension", 0.50),
}


def emotion_for_moment(
    event: str,
    perspective: str = "neutral",
    late_game: bool = False,
) -> tuple[Emotion, float]:
    """
    Return deterministic emotion and intensity for a match event.

    Args:
        event:
            Event trigger, such as "goal", "equaliser", "red_card",
            "big_chance", or "momentum_swing".

        perspective:
            "favourable", "unfavourable", or "neutral", relative to the viewer.

        late_game:
            When True, increase intensity by 0.10. The caller decides whether
            the match context qualifies as late game.

    Returns:
        A tuple (emotion, intensity), with intensity in [0.0, 1.0].

    Unknown event/perspective combinations fall back to neutral delivery.
    """
    event_key = str(event or "").strip().lower()
    perspective_key = str(perspective or "neutral").strip().lower()

    emotion, intensity = _EMOTION_TABLE.get(
        (event_key, perspective_key),
        ("neutral", 0.30),
    )

    if late_game:
        intensity = min(1.0, intensity + 0.10)

    return emotion, round(clamp01(intensity), 2)


# ===========================================================================
# 2. Emotion + intensity -> baseline prosody
# ===========================================================================

@dataclass(frozen=True)
class Prosody:
    """
    Relative prosody offsets for SSML.

    These values are percentage offsets, not absolute settings:
        rate=+12   means a +12% rate offset
        pitch=-4   means a -4% pitch offset
        volume=+10 means a +10% volume offset

    The selected voice and language affect the perceived result, so tune these
    starting values by listening to real narration.
    """

    rate: int
    pitch: int
    volume: int


# Initial values from the development notebook.
#
# At intensity 1.0 these are the maximum offsets before limits are applied.
# At intensity 0.0 the output returns to neutral offsets.
#
# Emotion must also be expressed through the wording and structure of the
# narration. Prosody alone cannot make flat or generic text compelling.

_EMOTION_PROSODY: dict[Emotion, Prosody] = {
    "neutral":        Prosody(0, 0, 0),
    "anticipation":   Prosody(12, 7, 8),
    "excitement":     Prosody(24, 14, 25),
    "shock":          Prosody(16, 15, 22),
    "relief":         Prosody(-8, -4, 10),
    "disappointment": Prosody(-18, -12, -15),
    "tension":        Prosody(10, 9, -8),
}


# Safety limits for the baseline SSML offsets.
# Avoid extreme speed, pitch and gain changes that can reduce intelligibility
# or make the performance sound cartoonish.
_LIMITS: dict[str, tuple[int, int]] = {
    "rate": (-25, 30),
    "pitch": (-15, 15),
    "volume": (-30, 30),
}


def prosody_for(
    emotion: str | Emotion,
    intensity: float,
) -> Prosody:
    """
    Convert emotion and intensity into bounded prosody offsets.

    Unknown emotion values fall back to neutral. AudioService should still
    validate emotion names against EMOTIONS before making this call.

    The returned offsets can be embedded in Azure SSML. If a selected voice
    supports expressive styles, ssml.py may additionally wrap the prosody
    with its advertised mstts:express-as style.
    """
    emotion_key = str(emotion or "neutral").strip().lower()

    full = _EMOTION_PROSODY.get(
        emotion_key,  # type: ignore[arg-type]
        _EMOTION_PROSODY["neutral"],
    )

    strength = clamp01(intensity)

    def scale(
        value: int,
        bounds: tuple[int, int],
    ) -> int:
        scaled = round(value * strength)
        return max(bounds[0], min(bounds[1], scaled))

    return Prosody(
        rate=scale(full.rate, _LIMITS["rate"]),
        pitch=scale(full.pitch, _LIMITS["pitch"]),
        volume=scale(full.volume, _LIMITS["volume"]),
    )


# ===========================================================================
# 3. Optional Azure speaking styles
# ===========================================================================

# Candidate styles, best preference first.
#
# A style is used ONLY when the selected voice's live Azure voice catalogue
# advertises it. Do not assume that every style works for every voice, locale,
# or region.
#
# These preferences are initial tuning choices. Verify their effect by
# listening; a style name alone does not guarantee a particular performance.

STYLE_PREFERENCE: dict[str, list[str]] = {
    "anticipation": ["hopeful", "excited", "cheerful"],
    "excitement": ["excited", "cheerful", "sports_commentary_excited"],
    "shock": ["excited", "shouting", "terrified"],
    "relief": ["hopeful", "cheerful", "chat"],
    "disappointment": ["sad", "disgruntled"],
    "tension": ["serious", "whispering", "hopeful"],
}


def build_style_map(
    catalog: dict[str, list[str]],
) -> dict[str, dict[str, str]]:
    """
    Select a preferred speaking style for each voice and supported emotion.

    Args:
        catalog:
            Mapping of Azure voice name to the StyleList advertised for that
            voice. Example:
                {
                    "en-US-ExampleNeural": ["cheerful", "excited", "sad"],
                    "sw-KE-ExampleNeural": [],
                }

    Returns:
        Mapping of voice -> emotion -> selected advertised style.

    Voices without a matching style are omitted. Their speech should use the
    bounded baseline prosody from prosody_for() instead.

    Style comparison is case-insensitive, but the exact advertised style
    spelling is preserved in the returned map.
    """
    result: dict[str, dict[str, str]] = {}

    for voice_id, advertised_styles in catalog.items():
        if not voice_id:
            continue

        # Retain the exact catalogue spelling for SSML, but match names without
        # regard to case.
        style_lookup = {
            style.casefold(): style
            for style in (advertised_styles or [])
            if isinstance(style, str) and style.strip()
        }

        if not style_lookup:
            continue

        selected: dict[str, str] = {}

        for emotion, preferences in STYLE_PREFERENCE.items():
            chosen = next(
                (
                    style_lookup[preferred.casefold()]
                    for preferred in preferences
                    if preferred.casefold() in style_lookup
                ),
                None,
            )

            if chosen is not None:
                selected[emotion] = chosen

        if selected:
            result[voice_id] = selected

    return result


__all__ = [
    "PROSODY_VERSION",
    "STYLE_PREFERENCE",
    "Prosody",
    "build_style_map",
    "clamp01",
    "emotion_for_moment",
    "prosody_for",
]

