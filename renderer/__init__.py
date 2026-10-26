
"""
Msimulizi production audio package.

Public API for:
- Audio request/result contracts
- Deterministic emotion and prosody
- Speech-text normalization and SSML
- Azure AI Speech synthesis
- Azure Blob Storage and local development storage
- Audio caching, retries, and rendering
- Configuration and metrics

This module only re-exports public symbols. It does not create clients,
read credentials, contact Azure, or start background tasks.
"""

from __future__ import annotations

# ---------------------------------------------------------------------------
# 1. Shared contracts
# ---------------------------------------------------------------------------

from .contract import (
    AudioRequest,
    AudioResult,
    AudioStore,
    BudgetGuard,
    Emotion,
    Language,
    LANGUAGES,
    EMOTIONS,
    SpeechEngine,
    SpeechError,
    StoredAudio,
    SynthesizedAudio,
)

# ---------------------------------------------------------------------------
# 2. Emotion and prosody
# ---------------------------------------------------------------------------

from .emotion import (
    PROSODY_VERSION,
    STYLE_PREFERENCE,
    Prosody,
    build_style_map,
    emotion_for_moment,
    prosody_for,
)

# ---------------------------------------------------------------------------
# 3. Speech-text normalization
# ---------------------------------------------------------------------------

from .speech_text import (
    TTS_TEXT_VERSION,
    prepare_tts_text,
)

# ---------------------------------------------------------------------------
# 4. SSML generation
# ---------------------------------------------------------------------------

from .ssml import (
    build_ssml,
)

# ---------------------------------------------------------------------------
# 5. Production speech engine
# ---------------------------------------------------------------------------

from .azure_engine import (
    AzureTtsEngine,
)

# ---------------------------------------------------------------------------
# 6. Audio storage
# ---------------------------------------------------------------------------

from .stores import (
    AzureBlobStore,
    LocalDirStore,
)

# ---------------------------------------------------------------------------
# 7. Audio rendering service
# ---------------------------------------------------------------------------

from .service import (
    AudioService,
    cache_key,
)

# ---------------------------------------------------------------------------
# 8. Metrics
# ---------------------------------------------------------------------------

from .metrics import (
    NullMetrics,
    OtelMetrics,
    default_metrics,
)

# ---------------------------------------------------------------------------
# 9. Configuration and production factory
# ---------------------------------------------------------------------------

from .config import (
    AudioSettings,
    DEFAULT_VOICES,
    build_audio_service,
)


__all__ = [
    # Contracts
    "AudioRequest",
    "AudioResult",
    "AudioStore",
    "BudgetGuard",
    "Emotion",
    "Language",
    "LANGUAGES",
    "EMOTIONS",
    "SpeechEngine",
    "SpeechError",
    "StoredAudio",
    "SynthesizedAudio",

    # Emotion and prosody
    "PROSODY_VERSION",
    "STYLE_PREFERENCE",
    "Prosody",
    "build_style_map",
    "emotion_for_moment",
    "prosody_for",

    # Speech text and SSML
    "TTS_TEXT_VERSION",
    "prepare_tts_text",
    "build_ssml",

    # Speech engine
    "AzureTtsEngine",

    # Storage
    "AzureBlobStore",
    "LocalDirStore",

    # Service
    "AudioService",
    "cache_key",

    # Metrics
    "NullMetrics",
    "OtelMetrics",
    "default_metrics",

    # Configuration
    "AudioSettings",
    "DEFAULT_VOICES",
    "build_audio_service",
]
