
"""
Azure SSML generation for Msimulizi football commentary.

Combines:
- Approved narration text
- Language and configured voice
- Deterministic emotion and intensity
- Bounded prosody settings
- Optional Azure speaking styles advertised by the selected voice

This module creates SSML only. It does not make network requests.
"""

from __future__ import annotations

import re
from xml.sax.saxutils import escape, quoteattr

from .contract import AudioRequest
from .emotion import clamp01, prosody_for
from .speech_text import prepare_tts_text


# Locale prefix in standard Azure Neural voice names:
#   sw-KE-ZuriNeural  -> sw-KE
#   en-GB-RyanNeural  -> en-GB
#   fr-FR-DeniseNeural -> fr-FR
_LOCALE_PREFIX_RE = re.compile(r"^([a-z]{2}-[A-Z]{2})-")

_FALLBACK_LOCALES = {
    "sw": "sw-KE",
    "en": "en-GB",
    "fr": "fr-FR",
}

# Characters prohibited by XML 1.0, excluding valid whitespace characters.
_INVALID_XML_RE = re.compile(
    r"[\x00-\x08\x0B\x0C\x0E-\x1F\uFFFE\uFFFF]"
)


def _locale_for_request(req: AudioRequest) -> str:
    """
    Resolve the SSML locale from the voice name.

    The configured voice locale takes precedence because it determines the
    pronunciation used by Azure. The request language provides a fallback.
    """
    voice = (req.voice_id or "").strip()
    match = _LOCALE_PREFIX_RE.match(voice)

    if match:
        return match.group(1)

    language = str(req.language or "en").lower()

    if language.startswith("sw"):
        return _FALLBACK_LOCALES["sw"]
    if language.startswith("fr"):
        return _FALLBACK_LOCALES["fr"]

    return _FALLBACK_LOCALES["en"]


def _check_voice_language(req: AudioRequest, locale: str) -> None:
    """
    Reject a clear mismatch between requested language and voice locale.

    This prevents an English voice being silently selected for Swahili
    narration. Custom voice names that do not expose a standard locale are
    handled through the fallback locale resolution above.
    """
    requested = str(req.language or "en").lower().split("-", maxsplit=1)[0]
    voice_language = locale.split("-", maxsplit=1)[0].lower()

    supported = {"sw", "en", "fr"}

    if requested in supported and requested != voice_language:
        raise ValueError(
            f"Language/voice mismatch: request language={requested!r}, "
            f"voice={req.voice_id!r}, resolved locale={locale!r}"
        )


def build_ssml(
    req: AudioRequest,
    style_map: dict[str, dict[str, str]] | None = None,
) -> str:
    """
    Build SSML for one approved narration request.

    `style_map` has this shape:
        {
            "en-US-ExampleNeural": {
                "excitement": "excited",
                "disappointment": "sad",
            }
        }

    Only pass styles discovered in the Azure voice catalogue. Voices without
    an appropriate advertised style use the baseline prosody settings.

    Raises:
        ValueError: If the voice is missing, the language is inconsistent,
                    or speech text is empty.
    """
    voice = (req.voice_id or "").strip()

    if not voice:
        raise ValueError("voice_id is required to build SSML")

    spoken = prepare_tts_text(req.text, req.language)
    spoken = _INVALID_XML_RE.sub("", spoken)

    if not spoken.strip():
        raise ValueError("Narration is empty after speech-text preparation")

    locale = _locale_for_request(req)
    _check_voice_language(req, locale)

    prosody = prosody_for(req.emotion, req.intensity)

    # escape() prevents text such as "A & B" or "the <defender>" from
    # becoming unintended XML markup.
    body = (
        f'<prosody rate="{prosody.rate:+d}%" '
        f'pitch="{prosody.pitch:+d}%" '
        f'volume="{prosody.volume:+d}%">'
        f"{escape(spoken)}"
        "</prosody>"
    )

    # Use a style only when it has been confirmed in the selected voice's
    # actual Azure catalogue. Styles are not assumed to exist for every locale.
    available_styles = (style_map or {}).get(voice, {})
    style = available_styles.get(str(req.emotion))

    if style:
        degree = round(0.5 + 1.5 * clamp01(req.intensity), 2)

        body = (
            f"<mstts:express-as style={quoteattr(style)} "
            f'styledegree="{degree}">'
            f"{body}"
            "</mstts:express-as>"
        )

    return (
        '<speak version="1.0" '
        'xmlns="http://www.w3.org/2001/10/synthesis" '
        'xmlns:mstts="https://www.w3.org/2001/mstts" '
        f'xml:lang="{locale}">'
        f"<voice name={quoteattr(voice)}>"
        f"{body}"
        "</voice>"
        "</speak>"
    )


__all__ = [
    "build_ssml",
]

