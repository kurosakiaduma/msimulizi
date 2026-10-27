
"""
Metrics for the Msimulizi audio service.

Records:
- audio_render_ms: time spent in AudioService.render(), including cache
  lookups and synthesis.
- audio_render_total: render requests grouped by outcome, language and emotion.
- audio_latency_ms: event timestamp to audio_update publication latency.
- quota_exceeded_count: requests refused by the audio budget guard.

The OpenTelemetry MeterProvider and exporter should be configured by the
application's existing observability setup. This module creates instruments
but does not configure an exporter or send telemetry to an external service.

OpenTelemetry is optional. NullMetrics allows the audio service to operate
when the OpenTelemetry API is not installed.
"""

from __future__ import annotations

import logging
import math
from typing import Any

from .contract import AudioRequest


logger = logging.getLogger("msimulizi.audio.metrics")


# ===========================================================================
# Null implementation
# ===========================================================================

class NullMetrics:
    """
    No-op metrics implementation.

    This is used in unit tests, minimal development environments, or
    deployments where OpenTelemetry instrumentation is disabled.
    """

    def record(
        self,
        outcome: str,
        ms: float,
        req: AudioRequest,
    ) -> None:
        """Record a render result. No-op."""
        return None

    def latency(
        self,
        ms: float,
        req: AudioRequest,
    ) -> None:
        """Record end-to-end audio latency. No-op."""
        return None

    def quota_exceeded(
        self,
        req: AudioRequest,
    ) -> None:
        """Record a budget refusal. No-op."""
        return None


# ===========================================================================
# OpenTelemetry implementation
# ===========================================================================

class OtelMetrics:
    """
    OpenTelemetry instruments for Msimulizi audio rendering.

    This class uses the application's currently configured MeterProvider.
    Configure the provider and exporter in the existing application
    observability/bootstrap code, not in this module.

    Metric dimensions are deliberately low-cardinality:
        outcome, language, emotion

    Do not add narration text, narration ID, card ID, match ID, or audio URL
    as metric attributes. Those belong in appropriately sampled logs or
    traces when needed.
    """

    METER_NAME = "msimulizi.audio"

    def __init__(self, meter: Any | None = None) -> None:
        if meter is None:
            from opentelemetry import metrics

            meter = metrics.get_meter(self.METER_NAME)

        self._render_latency = meter.create_histogram(
            name="audio_render_ms",
            unit="ms",
            description=(
                "Time spent rendering an audio request, including cache "
                "lookup and synthesis"
            ),
        )

        self._render_count = meter.create_counter(
            name="audio_render_total",
            unit="{request}",
            description="Number of audio render requests by outcome",
        )

        self._end_to_end_latency = meter.create_histogram(
            name="audio_latency_ms",
            unit="ms",
            description=(
                "Time from the source event timestamp to audio_update "
                "publication"
            ),
        )

        self._quota_count = meter.create_counter(
            name="quota_exceeded_count",
            unit="{request}",
            description="Number of audio requests refused by the budget guard",
        )

    @staticmethod
    def _attributes(
        req: AudioRequest,
        *,
        outcome: str | None = None,
    ) -> dict[str, str]:
        """
        Return bounded metric attributes.

        Request validation may have failed before a language or emotion was
        normalized, so guard against missing or invalid values here.
        """
        language = getattr(req, "language", None)
        emotion = getattr(req, "emotion", None)

        attrs = {
            "language": (
                language
                if language in {"sw", "en", "fr"}
                else "unknown"
            ),
            "emotion": (
                emotion
                if emotion in {
                    "neutral",
                    "anticipation",
                    "excitement",
                    "shock",
                    "relief",
                    "disappointment",
                    "tension",
                }
                else "unknown"
            ),
        }

        if outcome is not None:
            # Outcomes should come from the finite set emitted by AudioService,
            # rather than arbitrary exception messages.
            attrs["outcome"] = str(outcome)[:40]

        return attrs

    @staticmethod
    def _valid_duration(ms: float) -> float:
        """Return a non-negative finite measurement."""
        value = float(ms)

        if not math.isfinite(value) or value < 0:
            return 0.0

        return value

    def record(
        self,
        outcome: str,
        ms: float,
        req: AudioRequest,
    ) -> None:
        """
        Record render latency and the outcome counter.

        Expected outcomes include:
            synthesized, memo_hit, store_hit, coalesced, invalid, timeout,
            engine_error, store_error, breaker_open, budget, and bundle_hit.
        """
        duration = self._valid_duration(ms)
        attrs = self._attributes(req, outcome=outcome)

        self._render_latency.record(
            duration,
            attributes=attrs,
        )

        self._render_count.add(
            1,
            attributes=attrs,
        )

    def latency(
        self,
        ms: float,
        req: AudioRequest,
    ) -> None:
        """Record source-event-to-audio-update publication latency."""
        self._end_to_end_latency.record(
            self._valid_duration(ms),
            attributes=self._attributes(req),
        )

    def quota_exceeded(
        self,
        req: AudioRequest,
    ) -> None:
        """Increment the budget-refusal counter."""
        self._quota_count.add(
            1,
            attributes=self._attributes(req),
        )


# ===========================================================================
# Factory
# ===========================================================================

def default_metrics() -> NullMetrics | OtelMetrics:
    """
    Construct the default metrics implementation.

    If the OpenTelemetry API package is missing, return NullMetrics so
    instrumentation does not prevent the audio subsystem from starting.

    This does not mean telemetry is exported automatically. The application's
    MeterProvider/exporter must be configured separately.
    """
    try:
        return OtelMetrics()
    except ImportError:
        logger.info(
            "OpenTelemetry API is not installed; using NullMetrics"
        )
        return NullMetrics()


__all__ = [
    "NullMetrics",
    "OtelMetrics",
    "default_metrics",
]

