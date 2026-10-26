from __future__ import annotations

import hashlib
import inspect
import logging
import re
from pathlib import Path
from typing import Any, Awaitable, Callable, Protocol, runtime_checkable, cast

import yaml

from renderer.audio.contract import AudioRequest, AudioResult, Emotion
from renderer.audio.config import AudioSettings
from renderer.audio.emotion import emotion_for_moment
from renderer.audio.service import AudioService

logger = logging.getLogger(__name__)


@runtime_checkable
class AudioPublisherProtocol(Protocol):
    """Publisher contract for pushing ``audio_update`` messages."""

    def publish(self, payload: dict[str, Any], /) -> Any: ...


@runtime_checkable
class BlobStorageProtocol(Protocol):
    """Legacy blob-storage protocol retained for import compatibility."""

    def upload_bytes(self, name: str, payload: bytes, /) -> Any: ...
    def upload_blob(self, name: str, payload: bytes, /) -> Any: ...
    def put(self, name: str, payload: bytes, /) -> Any: ...


# The singleton is registered from the existing FastAPI lifespan. A separate
# settings reference lets the facade respect AUDIO_VOICE_* environment
# overrides instead of re-reading only the YAML defaults.
_audio_service: AudioService | None = None
_audio_settings: AudioSettings | None = None


def set_audio_service(
    service: AudioService | None,
    *,
    settings: AudioSettings | None = None,
) -> None:
    """Register (or clear) the process-wide AudioService.

    Call after ``build_audio_service()`` during application startup. On
    shutdown, clear the reference before closing the service. Passing None
    clears both the service and its settings.

    The registry is intentionally process-local. Each application worker
    gets one AudioService; shared Blob Storage provides cross-worker caching.
    """
    global _audio_service, _audio_settings
    _audio_service = service
    _audio_settings = settings if service is not None else None


def get_audio_service() -> AudioService:
    """Return the startup-configured service or raise a clear error."""
    if _audio_service is None:
        raise RuntimeError(
            "Msimulizi AudioService is not configured. Register it during the "
            "FastAPI lifespan with renderer.tts.set_audio_service()."
        )
    return _audio_service


def clear_audio_service(service: AudioService | None = None) -> None:
    """Clear the singleton, optionally only if it matches ``service``.

    The optional identity check protects against a late shutdown callback
    clearing a newer service registered by a replacement application context.
    """
    global _audio_service, _audio_settings
    if service is not None and _audio_service is not service:
        return
    _audio_service = None
    _audio_settings = None


def _config_path() -> Path:
    """Return the root Foundry config file that carries speech voice metadata."""
    return Path(__file__).resolve().parents[1] / "config" / "foundry_models.yaml"


def _load_speech_config() -> dict[str, Any]:
    """Load speech voice metadata from YAML, if present."""
    try:
        with _config_path().open("r", encoding="utf-8") as handle:
            loaded = yaml.safe_load(handle) or {}
    except OSError:
        return {}
    if not isinstance(loaded, dict):
        return {}
    speech = loaded.get("speech", {})
    return speech if isinstance(speech, dict) else {}


def voice_for_language(language: str, *, fallback: str | None = None) -> str:
    """Resolve the configured speech voice for a language/locale.

    Active AudioSettings (including environment overrides) takes precedence;
    YAML and built-in defaults preserve compatibility before service startup
    and for legacy callers.
    """
    key = (language or "en").strip().lower().replace("_", "-")

    if _audio_settings is not None:
        try:
            return _audio_settings.voice_for(key)
        except (KeyError, ValueError):
            pass

    config = _load_speech_config()

    if key.startswith("sw"):
        if "tz" in key or "tanzania" in key:
            return config.get("swahili_tz", {}).get(
                "voice", "sw-TZ-RehemaNeural"
            )
        return config.get("swahili_ke", {}).get(
            "voice", "sw-KE-ZuriNeural"
        )
    if key.startswith("fr"):
        return config.get("french", {}).get("voice", "fr-FR-DeniseNeural")
    if key.startswith("en"):
        return config.get("english", {}).get("voice", "en-US-AriaNeural")
    return fallback or "en-US-AriaNeural"


def select_voice_for_language(language: str, *, fallback: str | None = None) -> str:
    """Compatibility alias for callers expecting the longer helper name."""
    return voice_for_language(language, fallback=fallback)


def build_audio_key(*, language: str, voice: str, text: str) -> str:
    """Return the legacy deterministic blob key for callers using upload_audio.

    The main AudioService uses its richer cache key, including emotion,
    intensity, engine version, SSML/prosody version and prepared speech text.
    This legacy key is retained only for the public upload_audio helper.
    """
    resolved_language = _normalise_language(language)
    payload = f"{resolved_language}|{voice}|{text}".encode("utf-8")
    digest = hashlib.sha256(payload).hexdigest()
    return f"audio/{resolved_language}/{digest}.wav"


def _normalise_language(language: str | None) -> str:
    """Normalize common language and locale aliases to short project codes."""
    value = (language or "en").strip().lower().replace("_", "-")
    if value.startswith("sw"):
        return "sw"
    if value.startswith("fr"):
        return "fr"
    return "en"


async def _maybe_await(value: Any) -> Any:
    """Await a result when the callback returns an awaitable."""
    if inspect.isawaitable(value):
        return await cast(Awaitable[Any], value)
    return value


def _field(obj: Any, *names: str, default: Any = None) -> Any:
    """Read the first available field from a dict or object."""
    for name in names:
        if isinstance(obj, dict) and name in obj:
            value = obj[name]
        else:
            value = getattr(obj, name, None)
        if value is not None:
            return value
    return default


def _enum_text(value: Any) -> str:
    """Turn a string/enum-like event field into a normalized key."""
    if value is None:
        return ""
    value = getattr(value, "value", value)
    if not isinstance(value, str):
        value = getattr(value, "name", value)
    text = str(value).strip().lower()
    if "." in text:
        text = text.rsplit(".", 1)[-1]
    return re.sub(r"[^a-z0-9]+", "_", text).strip("_")


def _extract_event_context(card: Any) -> tuple[str, str, bool]:
    """Extract deterministic event/perspective inputs when the card has them.

    No emotion is inferred from free-form narration text. If the card has no
    reliable event type and viewer perspective, the policy safely falls back
    to neutral delivery.
    """
    event_obj = _field(card, "event", "moment", "moment_event", default=None)
    event_raw = _field(
        card,
        "event_type",
        "trigger",
        "moment_type",
        "event_key",
        default=None,
    )
    if event_raw is None and event_obj is not None:
        event_raw = _field(
            event_obj, "event_type", "trigger", "type", "key", "name", default=event_obj
        )

    event = _enum_text(event_raw)
    perspective_raw = _field(
        card,
        "viewer_perspective",
        "perspective",
        "supporter_perspective",
        default=None,
    )
    if perspective_raw is None and event_obj is not None:
        perspective_raw = _field(
            event_obj,
            "viewer_perspective",
            "perspective",
            default="neutral",
        )

    perspective = _enum_text(perspective_raw or "neutral")
    aliases = {
        "positive": "favourable",
        "favorable": "favourable",
        "for": "favourable",
        "beneficial": "favourable",
        "negative": "unfavourable",
        "unfavorable": "unfavourable",
        "against": "unfavourable",
        "harmful": "unfavourable",
        "none": "neutral",
        "unknown": "neutral",
    }
    perspective = aliases.get(perspective, perspective)
    if perspective not in {"favourable", "unfavourable", "neutral"}:
        perspective = "neutral"

    minute_raw = _field(card, "match_minute", "minute", default=None)
    if minute_raw is None and event_obj is not None:
        minute_raw = _field(event_obj, "match_minute", "minute", default=None)
    # A common injury-time value like "90+3" should still count as minute 90.
    match_minute: int | None = None
    if minute_raw is not None:
        match = re.match(r"^\s*(\d+)", str(minute_raw))
        if match:
            match_minute = int(match.group(1))
    late_game = match_minute is not None and match_minute >= 80

    return event, perspective, late_game


def _emotion_for_card(card: Any) -> tuple[Emotion, float]:
    """Use deterministic policy, not LLM-selected free-form emotion labels."""
    event, perspective, late_game = _extract_event_context(card)
    return emotion_for_moment(event, perspective, late_game)


def _priority_for_card(card: Any) -> int:
    """Resolve a safe integer priority from a card when available."""
    value = _field(card, "priority", default=1)
    try:
        return int(value)
    except (TypeError, ValueError):
        return 1


def _minute_for_card(card: Any) -> int:
    """Return a non-negative match minute or zero when it is unavailable."""
    event_obj = _field(card, "event", "moment", default=None)
    raw = _field(card, "match_minute", "minute", default=None)
    if raw is None and event_obj is not None:
        raw = _field(event_obj, "match_minute", "minute", default=None)
    match = re.match(r"^\s*(\d+)", str(raw)) if raw is not None else None
    return max(0, int(match.group(1))) if match else 0


def _make_request(
    *,
    card_id: str,
    language: str,
    text: str,
    voice: str | None,
    emotion: Emotion,
    intensity: float,
    match_minute: int,
    priority: int,
) -> AudioRequest:
    """Build the contract request shared by legacy facades and card rendering."""
    chosen_voice = voice or voice_for_language(language)
    return AudioRequest(
        narration_id=str(card_id),
        text=text,
        language=_normalise_language(language),  # type: ignore[arg-type]
        emotion=emotion,
        intensity=intensity,
        voice_id=chosen_voice,
        match_minute=match_minute,
        priority=priority,
    )


async def _publish_legacy_update(
    publisher: AudioPublisherProtocol | Any | None,
    *,
    card_id: str,
    match_seconds: float | None,
    payload: dict[str, Any],
) -> None:
    """Publish exactly the existing four-field audio_update payload.

    AudioService internally includes duration_ms in its callback payload. This
    adapter deliberately filters that field to preserve this module's current
    frontend/WebSocket contract:
        type, card_id, audio_url, match_seconds
    """
    if publisher is None:
        return

    legacy_payload = {
        "type": "audio_update",
        "card_id": card_id,
        "audio_url": payload.get("audio_url"),
        "match_seconds": match_seconds,
    }

    callback = getattr(publisher, "publish", None)
    if not callable(callback) and callable(publisher):
        callback = publisher
    if not callable(callback):
        logger.warning("Configured audio publisher has no callable publish method")
        return

    await _maybe_await(callback(legacy_payload))


async def _render_through_service(
    *,
    card_id: str,
    language: str,
    text: str,
    match_seconds: float | None,
    voice: str | None,
    publisher: AudioPublisherProtocol | Any | None,
    emotion: Emotion,
    intensity: float,
    match_minute: int = 0,
    priority: int = 1,
) -> str | None:
    """Run the request through the registered AudioService singleton."""
    try:
        service = get_audio_service()
        request = _make_request(
            card_id=card_id,
            language=language,
            text=text,
            voice=voice,
            emotion=emotion,
            intensity=intensity,
            match_minute=match_minute,
            priority=priority,
        )

        async def publish_adapter(payload: dict[str, Any]) -> None:
            await _publish_legacy_update(
                publisher,
                card_id=card_id,
                match_seconds=match_seconds,
                payload=payload,
            )

        # render_and_publish provides the service's end-to-end metric path and
        # still publishes audio_url=None on synthesis/storage failure. Its
        # callback above strips duration_ms to preserve the legacy event shape.
        result: AudioResult = await service.render_and_publish(
            request,
            card_id=card_id,
            match_seconds=float(match_seconds) if match_seconds is not None else 0.0,
            publish=publish_adapter,
        )

        return result.audio_path if result.success else None

    except Exception as exc:
        # Missing singleton / invalid wiring should not crash the caller's
        # overlay caption path. Preserve the historical null-update failure.
        logger.warning("TTS service failed for %s: %s", card_id, exc, exc_info=True)
        if publisher is not None:
            try:
                await _publish_legacy_update(
                    publisher,
                    card_id=card_id,
                    match_seconds=match_seconds,
                    payload={"audio_url": None},
                )
            except Exception:
                logger.warning("Could not publish null audio_update for %s", card_id, exc_info=True)
        return None


class AzureSpeechSynthesizer:
    """Compatibility facade backed by the process-wide AudioService.

    Constructor parameters are retained for existing callers. New production
    configuration belongs in AudioSettings/build_audio_service during startup;
    this class no longer creates another Speech client or Blob client.

    For full caching/retries/storage/publication, use synthesize_card_audio().
    The low-level synthesize()/upload_audio() methods remain for compatibility
    with older integrations that explicitly manage bytes.
    """

    def __init__(
        self,
        *,
        endpoint: str | None = None,
        api_key: str | None = None,
        storage_url: str | None = None,
        blob_client: BlobStorageProtocol | Any | None = None,
        publisher: AudioPublisherProtocol | Any | None = None,
        default_language: str = "en",
    ) -> None:
        # Retain the constructor signature and attributes for legacy callers.
        # Speech endpoint/key/storage are intentionally managed by the shared
        # service factory to prevent each wrapper creating duplicate clients.
        self.endpoint = endpoint
        self.api_key = api_key
        self.storage_url = storage_url
        self.blob_client = blob_client
        self.publisher = publisher
        self.default_language = default_language

        if endpoint or api_key or storage_url or blob_client is not None:
            logger.debug(
                "Legacy AzureSpeechSynthesizer connection arguments are retained "
                "for compatibility; the registered AudioService owns the "
                "production Speech and storage clients."
            )

    async def synthesize(
        self,
        text: str,
        *,
        language: str,
        voice: str | None = None,
    ) -> bytes:
        """Return raw synthesized bytes using the singleton's speech engine.

        This legacy low-level API does not store a clip. The normal production
        card path below should be used to obtain cache/retry/storage handling.
        """
        service = get_audio_service()
        req = _make_request(
            card_id="legacy-direct-synthesis",
            language=language or self.default_language,
            text=text,
            voice=voice,
            emotion="neutral",
            intensity=0.0,
            match_minute=0,
            priority=1,
        )
        audio = await service.engine.synthesize(req)
        return audio.data

    async def upload_audio(
        self,
        *,
        text: str,
        language: str,
        audio_bytes: bytes,
        voice: str | None = None,
    ) -> str | None:
        """Store raw bytes using the singleton's configured AudioStore.

        Retained for legacy call sites. New card rendering should use
        AudioService.render(), which provides the richer audio cache key.
        """
        service = get_audio_service()
        chosen_voice = voice or voice_for_language(language)
        legacy_name = build_audio_key(
            language=language,
            voice=chosen_voice,
            text=text,
        )
        # build_audio_key historically returns a name ending in .wav. The
        # AudioStore contract accepts extension-free keys and the extension
        # separately, so strip only the final suffix before storing.
        key = legacy_name[:-4] if legacy_name.lower().endswith(".wav") else legacy_name
        stored = await service.store.put(
            key,
            audio_bytes,
            duration_ms=None,
            ext="wav",
        )
        return stored.url

    async def publish_update(
        self,
        *,
        card_id: str,
        match_seconds: float | None,
        audio_url: str | None,
    ) -> None:
        """Emit the legacy four-field audio_update payload when configured."""
        if self.publisher is None:
            return
        await _publish_legacy_update(
            self.publisher,
            card_id=card_id,
            match_seconds=match_seconds,
            payload={"audio_url": audio_url},
        )

    async def synthesize_card_audio(
        self,
        *,
        card_id: str,
        language: str,
        text: str,
        match_seconds: float | None = None,
        voice: str | None = None,
        existing_audio_url: str | None = None,
    ) -> str | None:
        """Return a ready URL using the singleton service, or None on failure."""
        if existing_audio_url:
            return existing_audio_url

        return await _render_through_service(
            card_id=str(card_id),
            language=language or self.default_language,
            text=text,
            match_seconds=match_seconds,
            voice=voice,
            publisher=self.publisher,
            emotion="neutral",
            intensity=0.30,
        )

    async def __call__(
        self,
        *,
        card_id: str,
        language: str,
        text: str,
        match_seconds: float | None = None,
        voice: str | None = None,
        existing_audio_url: str | None = None,
    ) -> str | None:
        """Convenience alias for the most common synthesis call."""
        return await self.synthesize_card_audio(
            card_id=card_id,
            language=language,
            text=text,
            match_seconds=match_seconds,
            voice=voice,
            existing_audio_url=existing_audio_url,
        )


def _extract_text_for_language(card: Any, *, language: str) -> str:
    """Pull the relevant headline/body text from a rendered card payload."""
    if hasattr(card, "text"):
        card_text = getattr(card, "text")
    elif isinstance(card, dict):
        card_text = card.get("text", {})
    else:
        card_text = {}

    if isinstance(card_text, dict):
        row = (
            card_text.get(language)
            or card_text.get(_normalise_language(language))
            or card_text.get("en")
        )
        if isinstance(row, dict):
            headline = str(row.get("headline", ""))
            body = str(row.get("body", ""))
            if headline or body:
                return " ".join(part for part in (headline, body) if part).strip()

    if hasattr(card, "headline"):
        headline = getattr(card, "headline")
        body = getattr(card, "body", "")
        if headline or body:
            return " ".join(
                part for part in (str(headline), str(body)) if part
            ).strip()

    if isinstance(card, dict):
        headline = card.get("headline", "")
        body = card.get("body", "")
        if headline or body:
            return " ".join(
                part for part in (str(headline), str(body)) if part
            ).strip()

    return "match update"


async def synthesize_card_audio(
    card: Any,
    *,
    synthesizer: AzureSpeechSynthesizer | None = None,
    language: str | None = None,
    voice: str | None = None,
    publisher: AudioPublisherProtocol | Any | None = None,
    blob_client: BlobStorageProtocol | Any | None = None,
    storage_url: str | None = None,
) -> str | None:
    """Synthesize approved card text through the singleton AudioService.

    Public signature is retained for existing Renderer callers. The legacy
    blob_client/storage_url arguments remain accepted but storage is now owned
    by the registered AudioService, configured during application startup.
    """
    resolved_language = _normalise_language(
        language or _field(card, "language", default=None) or "en"
    )
    text = _extract_text_for_language(card, language=resolved_language)

    card_id = _field(card, "card_id", default="card") or "card"
    match_seconds = _field(card, "match_seconds", default=None)
    existing_audio_url = _field(card, "audio_url", default=None)

    if existing_audio_url:
        return str(existing_audio_url)

    # Preserve publisher precedence from the existing function, while also
    # allowing an explicitly passed publisher to override the facade's one.
    selected_publisher = publisher
    default_language = "en"
    if synthesizer is not None:
        if selected_publisher is None:
            selected_publisher = synthesizer.publisher
        default_language = synthesizer.default_language

    if language is None and not _field(card, "language", default=None):
        resolved_language = _normalise_language(default_language)

    if blob_client is not None or storage_url:
        logger.debug(
            "blob_client/storage_url parameters are retained for compatibility; "
            "storage is handled by the registered AudioService."
        )

    emotion, intensity = _emotion_for_card(card)
    return await _render_through_service(
        card_id=str(card_id),
        language=resolved_language,
        text=text,
        match_seconds=match_seconds,
        voice=voice or voice_for_language(resolved_language),
        publisher=selected_publisher,
        emotion=emotion,
        intensity=intensity,
        match_minute=_minute_for_card(card),
        priority=_priority_for_card(card),
    )


__all__ = [
    "AudioPublisherProtocol",
    "AzureSpeechSynthesizer",
    "BlobStorageProtocol",
    "build_audio_key",
    "clear_audio_service",
    "get_audio_service",
    "select_voice_for_language",
    "set_audio_service",
    "synthesize_card_audio",
    "voice_for_language",
]
