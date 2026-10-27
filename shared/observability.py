"""shared/observability.py — OpenTelemetry custom metrics for Msimulizi.

Instruments the backend with five counters/histograms exported to
Application Insights (via the Azure Monitor OpenTelemetry exporter when
configured, or a no-op in-process store for tests and offline runs).

Metrics
-------
card_latency_ms       Histogram — end-to-end latency from Event receipt to
                      OverlayCard delivery, in milliseconds.
audio_latency_ms      Histogram — latency from Event receipt to audio_url
                      available, in milliseconds.
verdict_pass_count    Counter  — Verifier verdicts that passed.
verdict_fail_count    Counter  — Verifier verdicts that failed.
fallback_count        Counter  — Fallback Lines emitted (template path).
quota_exceeded_count  Counter  — QuotaExceeded errors caught in the pipeline.

Usage
-----
from shared.observability import metrics

metrics.record_card_latency(latency_ms, language="sw", card_type="goal")
metrics.record_audio_latency(latency_ms)
metrics.record_verdict(passed=True)
metrics.record_fallback()
metrics.record_quota_exceeded()

Environment variables
---------------------
APPLICATIONINSIGHTS_CONNECTION_STRING — when set, metrics are exported to
    Azure Monitor via the azure-monitor-opentelemetry package.  When absent
    the module falls back to an in-process store so tests and local runs
    continue to work without Azure credentials.
"""

from __future__ import annotations

import logging
import os
from collections import defaultdict
from threading import Lock
from typing import Any

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# In-process metric store (fallback when OTEL SDK is not available)
# ---------------------------------------------------------------------------

class _InProcessStore:
    """Lightweight in-process metric accumulator used in tests and offline runs."""

    def __init__(self) -> None:
        self._lock = Lock()
        # histogram: name -> list[float]
        self._histograms: dict[str, list[float]] = defaultdict(list)
        # counter: name -> int
        self._counters: dict[str, int] = defaultdict(int)

    def record_histogram(self, name: str, value: float, **_attrs: Any) -> None:
        with self._lock:
            self._histograms[name].append(value)

    def increment_counter(self, name: str, delta: int = 1, **_attrs: Any) -> None:
        with self._lock:
            self._counters[name] += delta

    def percentile(self, name: str, pct: float) -> float | None:
        """Return the requested percentile (0.0–100.0) or None if no data."""
        with self._lock:
            data = list(self._histograms.get(name, []))
        if not data:
            return None
        sorted_data = sorted(data)
        if pct >= 100.0:
            return sorted_data[-1]
        idx = (pct / 100.0) * (len(sorted_data) - 1)
        lo, hi = int(idx), min(int(idx) + 1, len(sorted_data) - 1)
        return sorted_data[lo] + (sorted_data[hi] - sorted_data[lo]) * (idx - lo)

    def p50(self, name: str) -> float | None:
        return self.percentile(name, 50.0)

    def p95(self, name: str) -> float | None:
        return self.percentile(name, 95.0)

    def count(self, name: str) -> int:
        with self._lock:
            return self._counters.get(name, 0)

    def snapshot(self) -> dict[str, Any]:
        """Return a JSON-serialisable summary for the /review endpoint."""
        with self._lock:
            hist_copy = {k: list(v) for k, v in self._histograms.items()}
            cnt_copy = dict(self._counters)

        latency = []
        for metric_name in ("card_latency_ms", "audio_latency_ms"):
            data = hist_copy.get(metric_name, [])
            if data:
                s = sorted(data)
                p50_val = _percentile_sorted(s, 50.0)
                p95_val = _percentile_sorted(s, 95.0)
            else:
                p50_val = p95_val = 0.0
            latency.append({
                "label": "Card latency" if metric_name == "card_latency_ms" else "Audio latency",
                "p50_ms": round(p50_val),
                "p95_ms": round(p95_val),
            })

        return {
            "latency": latency,
            "verdict_pass": cnt_copy.get("verdict_pass_count", 0),
            "verdict_fail": cnt_copy.get("verdict_fail_count", 0),
            "fallback_count": cnt_copy.get("fallback_count", 0),
            "quota_exceeded_count": cnt_copy.get("quota_exceeded_count", 0),
        }

    def reset(self) -> None:
        """Reset all stored metrics (used in tests)."""
        with self._lock:
            self._histograms.clear()
            self._counters.clear()


def _percentile_sorted(sorted_data: list[float], pct: float) -> float:
    if not sorted_data:
        return 0.0
    if pct >= 100.0:
        return sorted_data[-1]
    idx = (pct / 100.0) * (len(sorted_data) - 1)
    lo, hi = int(idx), min(int(idx) + 1, len(sorted_data) - 1)
    return sorted_data[lo] + (sorted_data[hi] - sorted_data[lo]) * (idx - lo)


# ---------------------------------------------------------------------------
# Try to wire up real OpenTelemetry + Azure Monitor
# ---------------------------------------------------------------------------

def _try_setup_otel(connection_string: str) -> Any | None:
    """Attempt to configure Azure Monitor OTEL exporter.

    Returns the OpenTelemetry MeterProvider on success, or None on failure.
    """
    try:
        from azure.monitor.opentelemetry import configure_azure_monitor
        from opentelemetry import metrics as otel_metrics
        from opentelemetry.sdk.metrics import MeterProvider  # noqa: F401

        configure_azure_monitor(connection_string=connection_string)
        provider = otel_metrics.get_meter_provider()
        logger.info("[observability] Azure Monitor OTEL exporter configured")
        return provider
    except ImportError:
        logger.debug("[observability] azure-monitor-opentelemetry not installed — skipping OTEL")
        return None
    except Exception as exc:
        logger.warning("[observability] OTEL setup failed: %s", exc)
        return None


def _try_get_otel_meter() -> Any | None:
    """Return an OpenTelemetry Meter if the SDK is available."""
    try:
        from opentelemetry import metrics as otel_metrics
        return otel_metrics.get_meter("msimulizi", version="0.1.0")
    except ImportError:
        return None
    except Exception:
        return None


# ---------------------------------------------------------------------------
# Public metrics facade
# ---------------------------------------------------------------------------

class MsimuliziFacade:
    """Thin facade that records to both the in-process store and OTEL (if live).

    The in-process store is always written so that the /review endpoint and
    tests can read latency percentiles without requiring Azure credentials.
    """

    def __init__(self) -> None:
        self._store = _InProcessStore()
        self._otel_meter: Any | None = None
        self._otel_card_hist: Any | None = None
        self._otel_audio_hist: Any | None = None
        self._otel_verdict_pass: Any | None = None
        self._otel_verdict_fail: Any | None = None
        self._otel_fallback: Any | None = None
        self._otel_quota: Any | None = None

        conn_str = os.getenv("APPLICATIONINSIGHTS_CONNECTION_STRING", "").strip()
        if conn_str:
            _try_setup_otel(conn_str)
            meter = _try_get_otel_meter()
            if meter is not None:
                self._otel_meter = meter
                self._otel_card_hist = meter.create_histogram(
                    "card_latency_ms",
                    description="End-to-end latency from Event receipt to OverlayCard delivery",
                    unit="ms",
                )
                self._otel_audio_hist = meter.create_histogram(
                    "audio_latency_ms",
                    description="Latency from Event receipt to audio_url available",
                    unit="ms",
                )
                self._otel_verdict_pass = meter.create_counter(
                    "verdict_pass_count",
                    description="Number of Verifier verdicts that passed",
                )
                self._otel_verdict_fail = meter.create_counter(
                    "verdict_fail_count",
                    description="Number of Verifier verdicts that failed",
                )
                self._otel_fallback = meter.create_counter(
                    "fallback_count",
                    description="Number of Fallback Lines emitted",
                )
                self._otel_quota = meter.create_counter(
                    "quota_exceeded_count",
                    description="Number of QuotaExceeded errors caught",
                )
                logger.info("[observability] OTEL meters created")

    # ------------------------------------------------------------------
    # Recording helpers
    # ------------------------------------------------------------------

    def record_card_latency(
        self,
        latency_ms: float,
        *,
        language: str = "unknown",
        card_type: str = "unknown",
    ) -> None:
        self._store.record_histogram("card_latency_ms", latency_ms)
        if self._otel_card_hist is not None:
            try:
                self._otel_card_hist.record(
                    latency_ms,
                    {"language": language, "card_type": card_type},
                )
            except Exception:
                pass

    def record_audio_latency(self, latency_ms: float) -> None:
        self._store.record_histogram("audio_latency_ms", latency_ms)
        if self._otel_audio_hist is not None:
            try:
                self._otel_audio_hist.record(latency_ms)
            except Exception:
                pass

    def record_verdict(self, *, passed: bool) -> None:
        if passed:
            self._store.increment_counter("verdict_pass_count")
            if self._otel_verdict_pass is not None:
                try:
                    self._otel_verdict_pass.add(1)
                except Exception:
                    pass
        else:
            self._store.increment_counter("verdict_fail_count")
            if self._otel_verdict_fail is not None:
                try:
                    self._otel_verdict_fail.add(1)
                except Exception:
                    pass

    def record_fallback(self) -> None:
        self._store.increment_counter("fallback_count")
        if self._otel_fallback is not None:
            try:
                self._otel_fallback.add(1)
            except Exception:
                pass

    def record_quota_exceeded(self) -> None:
        self._store.increment_counter("quota_exceeded_count")
        if self._otel_quota is not None:
            try:
                self._otel_quota.add(1)
            except Exception:
                pass

    # ------------------------------------------------------------------
    # Read helpers (used by /review endpoint)
    # ------------------------------------------------------------------

    def snapshot(self) -> dict[str, Any]:
        return self._store.snapshot()

    def p50_card_latency_ms(self) -> float | None:
        return self._store.p50("card_latency_ms")

    def p95_card_latency_ms(self) -> float | None:
        return self._store.p95("card_latency_ms")

    def p50_audio_latency_ms(self) -> float | None:
        return self._store.p50("audio_latency_ms")

    def p95_audio_latency_ms(self) -> float | None:
        return self._store.p95("audio_latency_ms")


# Module-level singleton — import and use this everywhere.
metrics = MsimuliziFacade()

__all__ = ["metrics", "MsimuliziFacade", "_InProcessStore"]
