
"""
Shared contracts for the Msimulizi audio subsystem.

This module defines the data structures and protocols used by:
- emotion.py
- speech_text.py
- ssml.py
- azure_engine.py
- stores.py
- service.py

Keep this module independent of Azure SDKs, FastAPI, and application-specific
Renderer models. That allows the audio service to be unit-tested without
connecting to Azure.

Production engine:
    Azure AI Speech

Development engines:
    Chatterbox, MMS-TTS, and Edge TTS may implement the same SpeechEngine
    protocol outside the production runtime.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Callable, Literal, Protocol, get_args


# ===========================================================================
# Supported languages and emotions
# ===========================================================================

Language = Literal["sw", "en", "fr"]

Emotion = Literal[
    "neutral",
    "anticipation",
    "excitement",
    "shock",
    "relief",
    "disappointment",
    "tension",
]

# Runtime values used for request validation.
LANGUAGES: tuple[str, ...] = get_args(Language)
EMOTIONS: tuple[str, ...] = get_args(Emotion)


# ===========================================================================
# Budget guard
# ===========================================================================

# Call this immediately before a real synthesis request.
#
# The argument is the number of characters in the request text.
# The guard can raise a quota/budget exception when synthesis is not allowed.
#
# Cache hits should not invoke this callback.
BudgetGuard = Callable[[int], None]


# ===========================================================================
# Audio request and result
# ===========================================================================

@dataclass
class AudioRequest:
    """
    A request to synthesize an approved narration into speech.

    Attributes:
        narration_id:
            Stable identifier for this narration/card.

        text:
            Text to speak. The caller should provide approved narration,
            not unverified LLM output.

        language:
            Canonical language code: "sw", "en", or "fr".

        emotion:
            Deterministically selected emotional delivery.

        intensity:
            Emotion intensity from 0.0 to 1.0. AudioService normalizes and
            quantizes this value before generating a cache key.

        voice_id:
            Configured speech voice identifier. For Azure Speech this is
            normally a voice name such as "sw-KE-ZuriNeural".

        match_minute:
            Match minute associated with the narration, used for ordering
            and diagnostics.

        priority:
            Lower values indicate higher priority. For example, priority 1
            can be used for a goal call, while lower-priority background
            narration can use a larger value.
    """

    narration_id: str
    text: str
    language: Language
    emotion: Emotion
    intensity: float
    voice_id: str
    match_minute: int
    priority: int


@dataclass
class AudioResult:
    """
    Result of an audio-rendering request.

    The existing interface calls the location `audio_path`. In production,
    this field can contain the playable Blob Storage URL returned by the
    AudioStore. For a local development store, it can contain a filesystem
    path.

    A failed render returns success=False and normally has no audio_path.
    The failure must not invalidate or remove the approved caption.
    """

    narration_id: str
    audio_path: str | None
    duration_ms: int | None
    success: bool
    error: str | None = None


# ===========================================================================
# Engine and storage result objects
# ===========================================================================

@dataclass(frozen=True)
class SynthesizedAudio:
    """
    Raw audio returned by a speech engine.

    `data` contains the actual encoded audio bytes. Its format is determined
    by the engine's `audio_ext` attribute, for example "mp3" or "wav".

    `duration_ms` is optional because some engines may not provide a reliable
    duration estimate. A value of None means the duration is unknown.
    """

    data: bytes
    duration_ms: int | None


@dataclass(frozen=True)
class StoredAudio:
    """
    Location of an audio object after retrieval from or upload to storage.

    `url` is a playable URL in production when the storage configuration
    allows direct playback. For a local store, it is the local file path.

    `duration_ms` may be None if duration metadata was not available.
    """

    url: str
    duration_ms: int | None


# ===========================================================================
# Speech errors
# ===========================================================================

class SpeechError(Exception):
    """
    Error raised by a speech engine.

    Set transient=True only when retrying might succeed, for example:
    - a temporary network failure;
    - HTTP 429 throttling;
    - a temporary service-side HTTP 5xx response.

    Authentication failures, invalid SSML, unsupported voices and other
    permanent request errors should normally use transient=False.
    """

    def __init__(
        self,
        message: str,
        *,
        transient: bool = False,
    ) -> None:
        super().__init__(message)
        self.transient = transient


# ===========================================================================
# Speech-engine protocol
# ===========================================================================

class SpeechEngine(Protocol):
    """
    Interface implemented by each synthesis engine.

    `name` and `cache_version` are part of the cache identity. Increment the
    cache version whenever a change can alter the generated speech, including
    voice parameters, SSML construction, or engine-specific settings.

    `audio_ext` must match the actual encoding returned by synthesize().
    """

    name: str

    cache_version: str

    audio_ext: str

    async def synthesize(
        self,
        req: AudioRequest,
    ) -> SynthesizedAudio:
        """
        Synthesize one request.

        Raise SpeechError for expected synthesis failures. Mark an error
        transient only when the service may benefit from retrying.
        """
        ...

    async def aclose(self) -> None:
        """Release any engine-owned resources and network clients."""
        ...


# ===========================================================================
# Audio-store protocol
# ===========================================================================

class AudioStore(Protocol):
    """
    Interface implemented by audio-cache and audio-storage backends.

    Production:
        Azure Blob Storage.

    Development and unit tests:
        Local filesystem storage or a fake/in-memory store.

    Implementations must treat `key` and `ext` consistently across get()
    and put(). The key is generated by the audio service.
    """

    async def get(
        self,
        key: str,
        ext: str = "mp3",
    ) -> StoredAudio | None:
        """
        Return the stored object if it exists, otherwise None.

        A missing object is a cache miss, not an exceptional condition.
        """
        ...

    async def put(
        self,
        key: str,
        data: bytes,
        duration_ms: int | None,
        ext: str = "mp3",
    ) -> StoredAudio:
        """
        Store the completed audio and return its location.

        Implementations should not expose partially uploaded audio as
        a completed object.
        """
        ...

    async def aclose(self) -> None:
        """Close clients and release storage resources owned by the store."""
        ...

