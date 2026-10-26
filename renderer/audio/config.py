
"""
Configuration and factory for Msimulizi production audio.

Speech provider:
    Azure AI Speech REST API

Production audio storage:
    Azure Blob Storage using DefaultAzureCredential / managed identity

Development storage:
    LocalDirStore

Authentication:
    AZURE_SPEECH_KEY / SPEECH_API_KEY for local development
    SPEECH_USE_MANAGED_IDENTITY=true for DefaultAzureCredential
        (the default when no key is present)

Endpoint:
    AZURE_SPEECH_REGION
        or AZURE_SPEECH_ENDPOINT / SPEECH_ENDPOINT for a custom endpoint

Recommended production environment variable:
    AUDIO_BLOB_ACCOUNT_URL

Optional:
    AUDIO_BLOB_CONTAINER
    AUDIO_LOCAL_DIR
    AUDIO_TIMEOUT_S
    AZURE_SPEECH_REQUEST_TIMEOUT_S
    AUDIO_MAX_CONCURRENCY
    AUDIO_RETRIES
    AUDIO_RETRY_BACKOFF_S
    AUDIO_BREAKER_THRESHOLD
    AUDIO_BREAKER_COOLDOWN_S
    AUDIO_CACHE_SIZE
    AUDIO_VOICE_SW
    AUDIO_VOICE_SW_TZ
    AUDIO_VOICE_EN
    AUDIO_VOICE_FR
    AUDIO_VERIFY_VOICES
    AUDIO_STRICT_VOICE_CHECK
    AUDIO_BLOB_CACHE_CONTROL
    APP_ENV

Secrets must be injected through the deployment environment or a managed
secret system such as Azure Key Vault. Never commit a Speech key to source
control.
"""

from __future__ import annotations

import logging
import os

from dataclasses import dataclass, field
from pathlib import Path
from typing import Mapping

from .azure_engine import AzureTtsEngine
from .contract import BudgetGuard
from .metrics import default_metrics
from .service import AudioService
from .stores import (
    DEFAULT_CACHE_CONTROL,
    AzureBlobStore,
    LocalDirStore,
)


logger = logging.getLogger("msimulizi.audio.config")


# These match the fallback voices in the current renderer/tts.py.
# If config/foundry_models.yaml provides voice values, those values take
# precedence over these fallbacks when AudioSettings.from_env() is called.
DEFAULT_VOICES: dict[str, str] = {
    "sw": "sw-KE-ZuriNeural",
    "en": "en-US-AriaNeural",
    "fr": "fr-FR-DeniseNeural",
}

DEFAULT_SW_TZ_VOICE = "sw-TZ-RehemaNeural"


# ===========================================================================
# Environment parsing
# ===========================================================================

def _read_bool(
    env: Mapping[str, str],
    name: str,
    default: bool,
) -> bool:
    """Parse a conventional environment-variable boolean."""
    raw = env.get(name)

    if raw is None or not raw.strip():
        return default

    value = raw.strip().lower()

    if value in {"1", "true", "yes", "on"}:
        return True

    if value in {"0", "false", "no", "off"}:
        return False

    raise ValueError(
        f"{name} must be a boolean such as true/false; got {raw!r}"
    )


def _read_int(
    env: Mapping[str, str],
    name: str,
    default: int,
) -> int:
    """Read and validate an integer environment value."""
    raw = env.get(name)

    if raw is None or not raw.strip():
        return default

    try:
        return int(raw)
    except ValueError as exc:
        raise ValueError(f"{name} must be an integer") from exc


def _read_float(
    env: Mapping[str, str],
    name: str,
    default: float,
) -> float:
    """Read and validate a floating-point environment value."""
    raw = env.get(name)

    if raw is None or not raw.strip():
        return default

    try:
        return float(raw)
    except ValueError as exc:
        raise ValueError(f"{name} must be a number") from exc


def _optional_env(
    env: Mapping[str, str],
    name: str,
) -> str | None:
    """Return a stripped environment value, or None when unset/empty."""
    value = env.get(name)

    if value is None or not value.strip():
        return None

    return value.strip()


# ===========================================================================
# Existing Foundry YAML voice configuration
# ===========================================================================

def _foundry_config_path() -> Path:
    """
    Locate the existing project config/foundry_models.yaml.

    This file is at the repository root, two parents above this module:
        renderer/audio/config.py
        renderer/audio/
        renderer/
        repository root/
    """
    return (
        Path(__file__).resolve().parents[2]
        / "config"
        / "foundry_models.yaml"
    )


def _configured_voice_defaults() -> tuple[dict[str, str], str]:
    """
    Load voice defaults from the existing Foundry YAML when available.

    Expected structure:
        speech:
          swahili_ke:
            voice: sw-KE-ZuriNeural
          swahili_tz:
            voice: sw-TZ-RehemaNeural
          english:
            voice: en-US-AriaNeural
          french:
            voice: fr-FR-DeniseNeural

    Missing or invalid optional YAML does not prevent the code from using
    fallback voices. The deployment voice-catalogue check later confirms
    whether the selected voice names actually exist in the configured region.
    """
    voices = dict(DEFAULT_VOICES)
    sw_tz_voice = DEFAULT_SW_TZ_VOICE

    path = _foundry_config_path()

    if not path.is_file():
        return voices, sw_tz_voice

    try:
        import yaml

        with path.open("r", encoding="utf-8") as handle:
            root = yaml.safe_load(handle) or {}

    except ImportError:
        logger.warning(
            "PyYAML is unavailable; using built-in speech voice defaults"
        )
        return voices, sw_tz_voice

    except (OSError, ValueError):
        logger.warning(
            "Could not read speech voice configuration from %s",
            path,
            exc_info=True,
        )
        return voices, sw_tz_voice

    if not isinstance(root, dict):
        logger.warning(
            "Foundry YAML root is not a mapping; using fallback voices"
        )
        return voices, sw_tz_voice

    speech = root.get("speech", {})
    if not isinstance(speech, dict):
        return voices, sw_tz_voice

    sections = {
        "sw": "swahili_ke",
        "en": "english",
        "fr": "french",
    }

    for language, section_name in sections.items():
        section = speech.get(section_name, {})

        if not isinstance(section, dict):
            continue

        voice = section.get("voice")

        if isinstance(voice, str) and voice.strip():
            voices[language] = voice.strip()

    tanzania = speech.get("swahili_tz", {})

    if isinstance(tanzania, dict):
        configured_tz_voice = tanzania.get("voice")

        if isinstance(configured_tz_voice, str) and configured_tz_voice.strip():
            sw_tz_voice = configured_tz_voice.strip()

    return voices, sw_tz_voice


# ===========================================================================
# Settings
# ===========================================================================

@dataclass(frozen=True)
class AudioSettings:
    """Validated runtime settings for the audio service."""

    # Local development uses a Speech key. Production uses the container's
    # managed identity, which already has the Cognitive Services User role.
    speech_key: str | None = None
    use_managed_identity: bool = False

    # Supply a standard Azure region or a custom speech endpoint.
    speech_region: str | None = None
    speech_endpoint: str | None = None

    # Production storage account URL, for example:
    # https://myaccount.blob.core.windows.net
    blob_account_url: str | None = None
    blob_container: str = "audio"

    # Development-only local cache.
    local_dir: str = ".audio_cache"

    # Overall timeout covers queueing for a synthesis slot and all attempts.
    timeout_s: float = 8.0

    # Timeout for an individual Speech REST request.
    request_timeout_s: float = 5.0

    max_concurrency: int = 4
    retries: int = 1
    retry_backoff_s: float = 0.25

    breaker_threshold: int = 3
    breaker_cooldown_s: float = 30.0

    memo_size: int = 512

    voices: dict[str, str] = field(
        default_factory=lambda: dict(DEFAULT_VOICES)
    )
    swahili_tz_voice: str | None = DEFAULT_SW_TZ_VOICE

    verify_voices: bool = True
    strict_voice_check: bool = True

    cache_control: str = DEFAULT_CACHE_CONTROL

    environment: str = "development"

    def __post_init__(self) -> None:
        """Validate values even when the settings are created directly."""
        has_key = bool(self.speech_key and self.speech_key.strip())

        if not has_key and not self.use_managed_identity:
            raise ValueError(
                "An Azure Speech key or managed-identity authentication "
                "is required"
            )

        if self.use_managed_identity:
            # Managed identity and a static key are mutually exclusive. If a
            # key is present locally it is the more explicit choice.
            object.__setattr__(
                self,
                "use_managed_identity",
                not has_key,
            )

        if not (
            (self.speech_region and self.speech_region.strip())
            or (self.speech_endpoint and self.speech_endpoint.strip())
        ):
            raise ValueError(
                "Configure AZURE_SPEECH_REGION or AZURE_SPEECH_ENDPOINT"
            )

        if self.timeout_s <= 0:
            raise ValueError("timeout_s must be positive")

        if self.request_timeout_s <= 0:
            raise ValueError("request_timeout_s must be positive")

        if self.max_concurrency < 1:
            raise ValueError("max_concurrency must be at least 1")

        if self.retries < 0:
            raise ValueError("retries cannot be negative")

        if self.retry_backoff_s < 0:
            raise ValueError("retry_backoff_s cannot be negative")

        if self.breaker_threshold < 1:
            raise ValueError("breaker_threshold must be at least 1")

        if self.breaker_cooldown_s < 0:
            raise ValueError("breaker_cooldown_s cannot be negative")

        if self.memo_size < 0:
            raise ValueError("memo_size cannot be negative")

        required_languages = {"sw", "en", "fr"}

        missing_languages = required_languages - set(self.voices)
        if missing_languages:
            raise ValueError(
                "A voice must be configured for each supported language; "
                f"missing {sorted(missing_languages)}"
            )

        for language in required_languages:
            voice = self.voices.get(language)

            if not isinstance(voice, str) or not voice.strip():
                raise ValueError(
                    f"Voice configured for {language!r} cannot be empty"
                )

        # Copy the mutable dictionary so external code cannot mutate the
        # caller's dictionary after settings have been constructed.
        object.__setattr__(self, "voices", dict(self.voices))

    @classmethod
    def from_env(
        cls,
        env: Mapping[str, str] | None = None,
    ) -> "AudioSettings":
        """
        Build settings from process environment variables.

        Passing `env` explicitly makes configuration easy to unit-test.

        Authentication:
            AZURE_SPEECH_KEY or SPEECH_API_KEY for local development.
            Otherwise set SPEECH_USE_MANAGED_IDENTITY=true (the default when
            no key is present) to authenticate through DefaultAzureCredential.

        Endpoint:
            AZURE_SPEECH_REGION or AZURE_SPEECH_ENDPOINT/SPEECH_ENDPOINT.
        """
        if env is None:
            env = os.environ

        speech_key = (
            _optional_env(env, "AZURE_SPEECH_KEY")
            or _optional_env(env, "SPEECH_API_KEY")
        )

        speech_region = _optional_env(env, "AZURE_SPEECH_REGION")
        speech_endpoint = (
            _optional_env(env, "AZURE_SPEECH_ENDPOINT")
            or _optional_env(env, "SPEECH_ENDPOINT")
        )

        if not speech_region and not speech_endpoint:
            raise RuntimeError(
                "Set AZURE_SPEECH_REGION or AZURE_SPEECH_ENDPOINT "
                "(SPEECH_ENDPOINT is also accepted)"
            )

        use_managed_identity = _read_bool(
            env,
            "SPEECH_USE_MANAGED_IDENTITY",
            not bool(speech_key),
        )

        if not speech_key and not use_managed_identity:
            raise RuntimeError(
                "Azure Speech needs AZURE_SPEECH_KEY or "
                "SPEECH_USE_MANAGED_IDENTITY=true"
            )

        yaml_voices, sw_tz_voice = _configured_voice_defaults()

        voices = {
            language: (
                _optional_env(env, f"AUDIO_VOICE_{language.upper()}")
                or yaml_voices[language]
            )
            for language in ("sw", "en", "fr")
        }

        sw_tz_voice = (
            _optional_env(env, "AUDIO_VOICE_SW_TZ")
            or sw_tz_voice
        )

        environment = (
            _optional_env(env, "APP_ENV")
            or _optional_env(env, "ENVIRONMENT")
            or "development"
        ).lower()

        return cls(
            speech_key=speech_key,
            use_managed_identity=use_managed_identity,
            speech_region=speech_region,
            speech_endpoint=speech_endpoint,
            blob_account_url=(
                _optional_env(env, "AUDIO_BLOB_ACCOUNT_URL")
                or _optional_env(env, "STORAGE_ACCOUNT_URL")
            ),
            blob_container=(
                _optional_env(env, "AUDIO_BLOB_CONTAINER")
                or _optional_env(env, "AUDIO_CONTAINER")
                or "audio"
            ),
            local_dir=(
                _optional_env(env, "AUDIO_LOCAL_DIR") or ".audio_cache"
            ),
            timeout_s=_read_float(env, "AUDIO_TIMEOUT_S", 8.0),
            request_timeout_s=_read_float(
                env,
                "AZURE_SPEECH_REQUEST_TIMEOUT_S",
                5.0,
            ),
            max_concurrency=_read_int(
                env,
                "AUDIO_MAX_CONCURRENCY",
                4,
            ),
            retries=_read_int(env, "AUDIO_RETRIES", 1),
            retry_backoff_s=_read_float(
                env,
                "AUDIO_RETRY_BACKOFF_S",
                0.25,
            ),
            breaker_threshold=_read_int(
                env,
                "AUDIO_BREAKER_THRESHOLD",
                3,
            ),
            breaker_cooldown_s=_read_float(
                env,
                "AUDIO_BREAKER_COOLDOWN_S",
                30.0,
            ),
            memo_size=_read_int(env, "AUDIO_CACHE_SIZE", 512),
            voices=voices,
            swahili_tz_voice=sw_tz_voice,
            verify_voices=_read_bool(
                env,
                "AUDIO_VERIFY_VOICES",
                True,
            ),
            strict_voice_check=_read_bool(
                env,
                "AUDIO_STRICT_VOICE_CHECK",
                True,
            ),
            cache_control=(
                _optional_env(env, "AUDIO_BLOB_CACHE_CONTROL")
                or DEFAULT_CACHE_CONTROL
            ),
            environment=environment,
        )

    def voice_for(self, language: str) -> str:
        """
        Resolve a configured voice for a language/locale.

        Standard short language codes:
            sw, en, fr

        An explicitly regional Swahili locale can request the Tanzania voice:
            sw-TZ
            sw-Tanzania
        """
        value = (language or "en").strip().lower().replace("_", "-")

        if value.startswith("sw"):
            if "tz" in value or "tanzania" in value:
                return self.swahili_tz_voice or self.voices["sw"]
            return self.voices["sw"]

        if value.startswith("fr"):
            return self.voices["fr"]

        if value.startswith("en"):
            return self.voices["en"]

        raise ValueError(
            f"Unsupported language {language!r}; expected Swahili, "
            "English, or French"
        )


# ===========================================================================
# Voice-catalogue validation
# ===========================================================================

def _configured_voice_pairs(
    settings: AudioSettings,
) -> list[tuple[str, str]]:
    """Return language/voice pairs which need to be validated."""
    pairs = [
        (language, voice)
        for language, voice in settings.voices.items()
    ]

    if settings.swahili_tz_voice:
        pairs.append(("sw-TZ", settings.swahili_tz_voice))

    # Duplicate pairs do not need a duplicate catalogue lookup.
    return list(dict.fromkeys(pairs))


async def _check_configured_voices(
    engine: AzureTtsEngine,
    settings: AudioSettings,
) -> None:
    """
    Verify configured voice IDs and their language locales.

    Missing voices and clear language/locale mismatches are collected before
    raising an error. The caller decides whether a catalogue failure is fatal
    using `strict_voice_check`.
    """
    pairs = _configured_voice_pairs(settings)
    voice_ids = list(dict.fromkeys(voice for _, voice in pairs))

    result = await engine.load_voice_catalog(voice_ids)

    missing = list(result.get("missing", []))
    locales = result.get("locales", {})

    problems: list[str] = []

    if missing:
        problems.append(
            "voices missing from the configured Speech region: "
            + ", ".join(missing)
        )

    for language, voice in pairs:
        locale = locales.get(voice)

        # An absent locale entry should not be mistaken for a verified match.
        if not locale:
            continue

        expected = language.split("-", maxsplit=1)[0].lower()
        actual = str(locale).split("-", maxsplit=1)[0].lower()

        if expected != actual:
            problems.append(
                f"{voice!r} is locale {locale!r}, but {language!r} "
                "was expected"
            )

    if not problems:
        logger.info(
            "Azure Speech voice configuration validated for %d voice(s)",
            len(voice_ids),
        )
        return

    message = "; ".join(problems)

    if settings.strict_voice_check:
        raise RuntimeError(f"Azure Speech voice validation failed: {message}")

    logger.warning("Azure Speech voice validation warning: %s", message)


# ===========================================================================
# Production factory
# ===========================================================================

async def build_audio_service(
    settings: AudioSettings,
    *,
    budget: BudgetGuard | None = None,
    verify_voices: bool | None = None,
) -> AudioService:
    """
    Construct the production audio service.

    Production uses Azure Blob Storage. LocalDirStore is allowed when no
    Blob account URL is configured in a development environment.

    By default, the factory verifies voice availability at startup. Set
    verify_voices=False explicitly to skip the catalogue check, for example
    in an isolated unit test.

    Resource clients are cleaned up if initialization fails.
    """
    credential = None
    if settings.use_managed_identity:
        # Production Container Apps authenticate with the user-assigned
        # managed identity through AZURE_CLIENT_ID. DefaultAzureCredential
        # also supports developer credentials locally.
        try:
            from azure.identity import DefaultAzureCredential
        except ImportError as exc:
            raise RuntimeError(
                "azure-identity is required for managed-identity Speech"
            ) from exc

        credential = DefaultAzureCredential()

    engine = AzureTtsEngine(
        key=settings.speech_key,
        credential=credential,
        close_credential=credential is not None,
        region=settings.speech_region,
        base_url=settings.speech_endpoint,
        request_timeout_s=settings.request_timeout_s,
    )

    store = None

    try:
        if settings.blob_account_url:
            store = AzureBlobStore.from_account(
                settings.blob_account_url,
                container=settings.blob_container,
                cache_control=settings.cache_control,
            )

        else:
            environment = settings.environment.lower()

            if environment in {"prod", "production", "staging"}:
                raise RuntimeError(
                    "AUDIO_BLOB_ACCOUNT_URL is required in staging/production. "
                    "Local container storage may be ephemeral and is not a "
                    "durable production audio store."
                )

            logger.warning(
                "AUDIO_BLOB_ACCOUNT_URL is not set; using local development "
                "audio storage at %s",
                settings.local_dir,
            )
            store = LocalDirStore(
                settings.local_dir,
                cache_control=settings.cache_control,
            )

        should_verify = (
            settings.verify_voices
            if verify_voices is None
            else verify_voices
        )

        if should_verify:
            try:
                await _check_configured_voices(engine, settings)
            except Exception:
                if settings.strict_voice_check:
                    raise

                logger.warning(
                    "Could not strictly validate Azure Speech voices; "
                    "continuing with the configured voice names",
                    exc_info=True,
                )

        service = AudioService(
            engine,
            store,
            timeout_s=settings.timeout_s,
            max_concurrency=settings.max_concurrency,
            retries=settings.retries,
            retry_backoff_s=settings.retry_backoff_s,
            breaker_threshold=settings.breaker_threshold,
            breaker_cooldown_s=settings.breaker_cooldown_s,
            budget=budget,
            metrics=default_metrics(),
            memo_size=settings.memo_size,
            voice_for=settings.voice_for,
        )

        logger.info(
            "Msimulizi audio service created (environment=%s, storage=%s)",
            settings.environment,
            "azure-blob" if settings.blob_account_url else "local",
        )

        return service

    except BaseException:
        # If voice validation or store setup fails, do not leave open network
        # clients behind. Re-raise the original startup exception.
        try:
            await engine.aclose()
        except Exception:
            logger.warning(
                "Failed to close Azure Speech client during startup rollback",
                exc_info=True,
            )

        if store is not None:
            try:
                await store.aclose()
            except Exception:
                logger.warning(
                    "Failed to close audio store during startup rollback",
                    exc_info=True,
                )

        raise


__all__ = [
    "AudioSettings",
    "DEFAULT_VOICES",
    "build_audio_service",
]

