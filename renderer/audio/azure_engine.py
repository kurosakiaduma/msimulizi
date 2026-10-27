
"""
Azure AI Speech REST engine for Msimulizi.

Features:
- Asynchronous SSML synthesis using httpx
- Real MP3 response bytes
- Region-based or custom-domain endpoint configuration
- Transient failure classification for retry handling
- Azure voice-catalogue discovery
- Style selection based on the live voice catalogue
- Cache-version tracking

This engine implements the SpeechEngine protocol from contract.py.

Required package:
    httpx

The Speech key must come from the application environment or Key Vault.
Never hard-code it in this module.
"""

from __future__ import annotations

import asyncio
import hashlib
import inspect
import json
import logging
import re
from typing import Any
from urllib.parse import urlsplit

import httpx

from .contract import AudioRequest, SpeechError, SynthesizedAudio
from .emotion import build_style_map
from .ssml import build_ssml


logger = logging.getLogger("msimulizi.audio.azure")


# Azure output format:
# 24 kHz, 48 kbit/s, mono MP3.
_OUTPUT_FORMAT = "audio-24khz-48kbitrate-mono-mp3"
_BITRATE_KBPS = 48

# Bump when request headers, endpoint behaviour, or audio format changes.
_ENGINE_VERSION = "azure-rest-v1"


def _make_endpoints(
    *,
    region: str | None,
    base_url: str | None,
) -> tuple[str, str]:
    """
    Return (synthesis_url, voices_list_url).

    Supported configurations:

    Region:
        region="westeurope"

    Custom domain/resource endpoint:
        base_url="https://<your-speech-resource>.cognitiveservices.azure.com"

    A base_url ending in a known Cognitive Services path is also supported.

    For region-based deployments, use the region shown for your Speech
    resource, not the Azure resource name.
    """
    if base_url:
        base = base_url.strip().rstrip("/")

        parsed = urlsplit(base)
        if parsed.scheme not in {"https", "http"} or not parsed.netloc:
            raise ValueError(
                "base_url must be an absolute HTTP(S) URL"
            )

        if parsed.query or parsed.fragment:
            raise ValueError(
                "base_url must not contain a query string or fragment"
            )

        # Allow a caller to supply the complete synthesis endpoint.
        if base.endswith("/tts/cognitiveservices/v1"):
            synthesis_url = base
            voices_url = base.removesuffix("/v1") + "/voices/list"
            return synthesis_url, voices_url

        if base.endswith("/cognitiveservices/v1"):
            synthesis_url = base
            voices_url = base.removesuffix("/v1") + "/voices/list"
            return synthesis_url, voices_url

        # Allow callers to supply the endpoint root rather than /v1.
        if base.endswith("/tts/cognitiveservices"):
            root = base
        elif base.endswith("/cognitiveservices"):
            root = base
        else:
            # A custom Cognitive Services resource endpoint normally requires
            # the TTS path. A regional TTS hostname is handled separately.
            hostname = (parsed.hostname or "").lower()

            if hostname.endswith(".tts.speech.microsoft.com"):
                root = base + "/cognitiveservices"
            else:
                root = base + "/tts/cognitiveservices"

        return (
            f"{root}/v1",
            f"{root}/voices/list",
        )

    if not region or not region.strip():
        raise ValueError(
            "Provide an Azure Speech region or base_url"
        )

    clean_region = region.strip().lower()

    # Avoid accepting arbitrary URLs through the region parameter.
    if not re.fullmatch(r"[a-z0-9-]+", clean_region):
        raise ValueError(
            "region must be a region identifier, for example 'westeurope'"
        )

    root = (
        f"https://{clean_region}.tts.speech.microsoft.com"
        "/cognitiveservices"
    )

    return f"{root}/v1", f"{root}/voices/list"


class AzureTtsEngine:
    """
    Azure AI Speech engine that implements SpeechEngine.

    Attributes:
        name:
            Used by AudioService when constructing cache keys.

        audio_ext:
            "mp3", matching the configured Azure response format.

        cache_version:
            Changes when the output format or resolved style configuration
            changes.
    """

    name = "azure"
    audio_ext = "mp3"

    def __init__(
        self,
        *,
        key: str | None = None,
        credential: Any | None = None,
        close_credential: bool = False,
        region: str | None = None,
        base_url: str | None = None,
        client: httpx.AsyncClient | Any | None = None,
        style_map: dict[str, dict[str, str]] | None = None,
        request_timeout_s: float = 5.0,
    ) -> None:
        clean_key = (key or "").strip()

        if not clean_key and credential is None:
            raise ValueError(
                "Azure Speech needs a subscription key or an Azure credential"
            )

        if request_timeout_s <= 0:
            raise ValueError("request_timeout_s must be greater than zero")

        self._synth_url, self._voices_url = _make_endpoints(
            region=region,
            base_url=base_url,
        )

        self._key = clean_key or None
        self._credential = credential
        self._close_credential = close_credential
        self.style_map = style_map or {}
        self._owns_client = client is None

        if client is None:
            self._client = httpx.AsyncClient(
                timeout=httpx.Timeout(request_timeout_s),
            )
        else:
            # Allows tests or the application to inject a shared HTTP client.
            self._client = client

    @property
    def cache_version(self) -> str:
        """
        Cache version including the output format and selected speaking styles.

        If the live catalogue changes the chosen style for a voice, the cache
        identity changes as well.
        """
        identity = {
            "engine": _ENGINE_VERSION,
            "format": _OUTPUT_FORMAT,
            "styles": self.style_map,
        }

        encoded = json.dumps(
            identity,
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
        ).encode("utf-8")

        digest = hashlib.sha256(encoded).hexdigest()[:10]
        return f"{_ENGINE_VERSION}-{digest}"

    async def _auth_headers(self) -> dict[str, str]:
        """
        Return authentication headers for Azure Speech.

        A configured key wins. Otherwise the engine obtains an Entra ID token
        through the supplied credential (managed identity in Container Apps).
        """
        if self._key:
            return {"Ocp-Apim-Subscription-Key": self._key}

        if self._credential is None:  # pragma: no cover - constructor guard
            raise SpeechError("Azure Speech credential is not configured")

        scope = "https://cognitiveservices.azure.com/.default"

        try:
            getter = self._credential.get_token

            if inspect.iscoroutinefunction(getter):
                token = await getter(scope)
            else:
                # DefaultAzureCredential is synchronous; keep the event loop
                # free while it may refresh a token over the network.
                token = await asyncio.to_thread(getter, scope)
        except Exception as exc:
            raise SpeechError(
                "Could not acquire an Azure Speech access token: "
                f"{type(exc).__name__}"
            ) from exc

        access_token = getattr(token, "token", None)

        if not isinstance(access_token, str) or not access_token:
            raise SpeechError(
                "Azure Speech credential returned an empty access token"
            )

        return {"Authorization": f"Bearer {access_token}"}

    async def _headers(
        self,
        *,
        content_type: str | None = None,
    ) -> dict[str, str]:
        """Headers shared by Speech synthesis requests."""
        headers = await self._auth_headers()
        headers["User-Agent"] = "msimulizi-audio"

        if content_type:
            headers["Content-Type"] = content_type

        return headers

    @staticmethod
    def _duration_ms(audio_bytes: bytes) -> int:
        """
        Estimate duration from the configured 48 kbit/s MP3 bitrate.

        This is an approximation. If precise duration is required, use an audio
        metadata decoder as part of a separate post-processing stage.
        """
        return int(len(audio_bytes) * 8 / _BITRATE_KBPS)

    @staticmethod
    def _raise_for_http_status(
        status_code: int,
        response_text: str = "",
        *,
        operation: str,
    ) -> None:
        """
        Raise a SpeechError with retry classification.

        Transient:
            HTTP 408, 429, and 5xx.

        Normally permanent until configuration/input is corrected:
            HTTP 400, 401, 403, 404, and other 4xx responses.
        """
        detail = " ".join((response_text or "").split())[:300]

        if status_code == 408 or status_code == 429 or 500 <= status_code <= 599:
            raise SpeechError(
                f"Azure Speech {operation} returned HTTP {status_code}"
                + (f": {detail}" if detail else ""),
                transient=True,
            )

        if status_code in (401, 403):
            raise SpeechError(
                f"Azure Speech {operation} returned HTTP {status_code}; "
                "check the key, resource, and endpoint/region configuration"
            )

        raise SpeechError(
            f"Azure Speech {operation} returned HTTP {status_code}"
            + (f": {detail}" if detail else "")
        )

    async def synthesize(
        self,
        req: AudioRequest,
    ) -> SynthesizedAudio:
        """
        Synthesize narration and return actual MP3 bytes.

        AudioService is responsible for outer timeouts, retries, cache lookups,
        and storage. This method does not upload blobs or publish WebSocket
        events.
        """
        try:
            ssml = build_ssml(req, self.style_map)
        except (TypeError, ValueError) as exc:
            raise SpeechError(
                f"Invalid SSML input for {req.narration_id}: {exc}"
            ) from exc

        try:
            headers = await self._headers(
                content_type="application/ssml+xml",
            )
            headers["X-Microsoft-OutputFormat"] = _OUTPUT_FORMAT

            response = await self._client.post(
                self._synth_url,
                content=ssml.encode("utf-8"),
                headers=headers,
            )
        except httpx.RequestError as exc:
            # Includes network and HTTP-client timeout errors.
            raise SpeechError(
                f"Azure Speech network error: {type(exc).__name__}",
                transient=True,
            ) from exc

        if response.status_code != 200:
            self._raise_for_http_status(
                response.status_code,
                response.text,
                operation="synthesis",
            )

        audio_bytes = response.content

        if not audio_bytes:
            raise SpeechError(
                "Azure Speech returned an empty audio response",
                transient=True,
            )

        return SynthesizedAudio(
            data=audio_bytes,
            duration_ms=self._duration_ms(audio_bytes),
        )

    async def load_voice_catalog(
        self,
        voice_ids: list[str],
    ) -> dict[str, Any]:
        """
        Verify requested voice names and load their available styles.

        Returns:
            {
                "missing": [...],
                "styles": {voice_name: [available_style_names, ...]},
                "locales": {voice_name: locale},
            }

        The engine's style_map is rebuilt from the live catalogue. When a
        voice advertises no applicable style, SSML generation uses prosody
        without an express-as wrapper.

        A catalogue failure should be handled by the application according to
        its readiness policy. Do not silently treat a failed request as proof
        that all configured voices are valid.
        """
        if not voice_ids:
            self.style_map = {}
            return {
                "missing": [],
                "styles": {},
                "locales": {},
            }

        headers = await self._headers()

        try:
            response = await self._client.get(
                self._voices_url,
                headers=headers,
            )
        except httpx.RequestError as exc:
            raise SpeechError(
                f"Azure Speech voice catalogue network error: "
                f"{type(exc).__name__}",
                transient=True,
            ) from exc

        if response.status_code != 200:
            self._raise_for_http_status(
                response.status_code,
                response.text,
                operation="voice catalogue",
            )

        try:
            rows = response.json()
        except ValueError as exc:
            raise SpeechError(
                "Azure Speech returned invalid JSON for the voice catalogue"
            ) from exc

        if not isinstance(rows, list):
            raise SpeechError(
                "Azure Speech voice catalogue response was not a list"
            )

        catalog: dict[str, dict[str, Any]] = {}

        for row in rows:
            if not isinstance(row, dict):
                continue

            short_name = row.get("ShortName")
            if not isinstance(short_name, str) or not short_name:
                continue

            style_list = row.get("StyleList") or []
            if not isinstance(style_list, list):
                style_list = []

            catalog[short_name] = {
                "locale": row.get("Locale"),
                "styles": [
                    style for style in style_list
                    if isinstance(style, str)
                ],
            }

        requested = list(dict.fromkeys(voice_ids))

        missing = [
            voice_id for voice_id in requested
            if voice_id not in catalog
        ]

        available_styles = {
            voice_id: catalog[voice_id]["styles"]
            for voice_id in requested
            if voice_id in catalog
        }

        available_locales = {
            voice_id: catalog[voice_id]["locale"]
            for voice_id in requested
            if voice_id in catalog
        }

        self.style_map = build_style_map(available_styles)

        logger.info(
            "Azure Speech catalogue checked: %d requested, %d missing, "
            "%d with speaking styles",
            len(requested),
            len(missing),
            len(self.style_map),
        )

        return {
            "missing": missing,
            "styles": available_styles,
            "locales": available_locales,
        }

    async def aclose(self) -> None:
        """
        Close the owned HTTP client.

        An injected client is owned by the caller and will not be closed here.
        """
        if self._owns_client:
            await self._client.aclose()

        if self._close_credential and self._credential is not None:
            closer = getattr(self._credential, "close", None)
            if not callable(closer):
                closer = getattr(self._credential, "aclose", None)

            if callable(closer):
                result = closer()
                if inspect.isawaitable(result):
                    await result


__all__ = [
    "AzureTtsEngine",
]

