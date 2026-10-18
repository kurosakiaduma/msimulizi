"""
shared/budget.py — token-bucket rate limits for LLM and Speech calls.

Design points:
- Per-minute and per-day token buckets for each resource type (``"llm"`` and
  ``"speech"``).
- When a bucket is exhausted, ``consume()`` raises ``QuotaExceeded``.
- ``live_llm_allowed(speed)`` returns ``False`` when the replay speed exceeds
  4x, disabling live LLM calls per Requirement 13.6.
- Limits are configurable at construction time for easy testing.
- All state is in-memory and per-process (no Redis).  A single instance is
  shared across the application via the module-level ``budget`` singleton.
"""

from __future__ import annotations

import time
from dataclasses import dataclass, field

from shared.foundry_client import QuotaExceeded

# ---------------------------------------------------------------------------
# Live LLM speed threshold (Req 13.6)
# ---------------------------------------------------------------------------

_MAX_LIVE_LLM_SPEED = 4.0


# ---------------------------------------------------------------------------
# Token bucket
# ---------------------------------------------------------------------------

@dataclass
class _Bucket:
    """
    A simple replenishing token bucket.

    ``capacity`` tokens are available per ``window_seconds``.  Tokens refill
    linearly over time.  ``consume(n)`` subtracts *n* tokens; raises
    ``QuotaExceeded`` if fewer than *n* remain.
    """

    capacity: float               # max tokens in the bucket
    window_seconds: float         # refill window length in seconds
    _tokens: float = field(init=False)
    _last_refill: float = field(init=False)

    def __post_init__(self) -> None:
        self._tokens = float(self.capacity)
        self._last_refill = time.monotonic()

    def _refill(self) -> None:
        now = time.monotonic()
        elapsed = now - self._last_refill
        added = (elapsed / self.window_seconds) * self.capacity
        self._tokens = min(self.capacity, self._tokens + added)
        self._last_refill = now

    def consume(self, amount: float = 1.0, *, resource: str = "") -> None:
        """
        Consume *amount* tokens.

        Raises
        ------
        QuotaExceeded
            If fewer than *amount* tokens are available.
        """
        self._refill()
        if self._tokens < amount:
            raise QuotaExceeded(
                f"Budget exhausted for resource {resource!r} "
                f"(requested {amount}, available {self._tokens:.1f})",
                agent=resource,
            )
        self._tokens -= amount

    @property
    def available(self) -> float:
        self._refill()
        return self._tokens


# ---------------------------------------------------------------------------
# BudgetGuard
# ---------------------------------------------------------------------------

_SECONDS_PER_MINUTE = 60.0
_SECONDS_PER_DAY = 86_400.0


class BudgetGuard:
    """
    Per-minute and per-day token buckets for LLM and Speech calls.

    Parameters
    ----------
    llm_per_minute:
        Max LLM calls (or tokens — caller decides the unit) per minute.
    llm_per_day:
        Max LLM calls (or tokens) per day.
    speech_per_minute:
        Max Speech synthesis calls per minute.
    speech_per_day:
        Max Speech synthesis calls per day.
    """

    def __init__(
        self,
        *,
        llm_per_minute: float = 60.0,
        llm_per_day: float = 5_000.0,
        speech_per_minute: float = 30.0,
        speech_per_day: float = 2_000.0,
    ) -> None:
        self._llm_minute = _Bucket(llm_per_minute, _SECONDS_PER_MINUTE)
        self._llm_day = _Bucket(llm_per_day, _SECONDS_PER_DAY)
        self._speech_minute = _Bucket(speech_per_minute, _SECONDS_PER_MINUTE)
        self._speech_day = _Bucket(speech_per_day, _SECONDS_PER_DAY)

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def consume_llm(self, amount: float = 1.0) -> None:
        """
        Consume *amount* LLM units from both the per-minute and per-day buckets.

        Raises ``QuotaExceeded`` if either bucket is exhausted.
        """
        self._llm_minute.consume(amount, resource="llm_per_minute")
        self._llm_day.consume(amount, resource="llm_per_day")

    def consume_speech(self, amount: float = 1.0) -> None:
        """
        Consume *amount* Speech units from both the per-minute and per-day buckets.

        Raises ``QuotaExceeded`` if either bucket is exhausted.
        """
        self._speech_minute.consume(amount, resource="speech_per_minute")
        self._speech_day.consume(amount, resource="speech_per_day")

    def live_llm_allowed(self, speed: float) -> bool:
        """
        Return ``True`` if live LLM calls are allowed at *speed*.

        Live LLM calls are disabled above ``_MAX_LIVE_LLM_SPEED`` (4.0×) per
        Requirement 13.6 — at high replay speeds the system must serve cached
        narration or Fallback Lines instead.
        """
        return speed <= _MAX_LIVE_LLM_SPEED

    # ------------------------------------------------------------------
    # Diagnostic helpers (useful for monitoring / tests)
    # ------------------------------------------------------------------

    @property
    def llm_minute_available(self) -> float:
        return self._llm_minute.available

    @property
    def llm_day_available(self) -> float:
        return self._llm_day.available

    @property
    def speech_minute_available(self) -> float:
        return self._speech_minute.available

    @property
    def speech_day_available(self) -> float:
        return self._speech_day.available


# ---------------------------------------------------------------------------
# Module-level singleton
# ---------------------------------------------------------------------------

budget = BudgetGuard()
