"""
shared/session_clock.py — replay clock used by each session.

The viewer clock is anchored to a wall-clock timestamp and a match-time offset.
This keeps the UI clock stable across speed changes and restarts without any
need to track a global epoch.
"""

from __future__ import annotations

import time
from dataclasses import dataclass, field
from typing import Any


@dataclass
class SessionClock:
    """Track the viewer's match time for one replay session.

    ``anchor_wall`` is the wall-clock timestamp when the current anchor was set.
    ``anchor_match`` is the match time at that same instant. Reading the clock via
    ``match_time()`` converts elapsed wall time into match time using the current
    speed multiplier.

    A replay speed is allowed to vary between 0.1x and 4x. The lookahead used by
    the adapter is intentionally based on wall-clock time: at higher speeds, the
    pipeline emits further into the future so it remains roughly 10 seconds ahead
    of the viewer clock.
    """

    anchor_wall: float = field(default_factory=time.monotonic)
    anchor_match: float = 0.0
    speed: float = 1.0

    def __post_init__(self) -> None:
        """Normalise the speed multiplier and guard against invalid values."""
        self.speed = self._normalise_speed(self.speed)

    @staticmethod
    def _normalise_speed(speed: float) -> float:
        """Clamp the speed into the supported range for replay playback."""
        value = float(speed)
        if value <= 0:
            raise ValueError("SessionClock speed must be greater than zero")
        return min(max(value, 0.1), 4.0)

    def match_time(self, now: float | None = None) -> float:
        """Return the current viewer match time in seconds."""
        wall_now = time.monotonic() if now is None else float(now)
        return self.anchor_match + (wall_now - self.anchor_wall) * self.speed

    def wall_time_for(self, match_seconds: float) -> float:
        """Convert a match-second value to the wall-clock time at the current speed."""
        return self.anchor_wall + (float(match_seconds) - self.anchor_match) / self.speed

    def lookahead_limit(self, lookahead_seconds: float = 10.0, now: float | None = None) -> float:
        """Return the event window end for the adapter's replay lookahead.

        The adapter keeps roughly ``lookahead_seconds`` of real time available in
        front of the viewer. Because that "real time" window is scaled by the replay
        speed, the corresponding match-time window grows as ``lookahead_seconds * speed``.
        """
        return self.match_time(now) + float(lookahead_seconds) * self.speed

    def update(self, new_speed: float) -> float:
        """Change the replay speed while preserving the current match position."""
        current = self.match_time()
        self.speed = self._normalise_speed(new_speed)
        self.anchor_match = current
        self.anchor_wall = time.monotonic()
        return self.match_time()

    def restart(self) -> float:
        """Re-anchor the clock at the start of the match without changing speed."""
        self.anchor_wall = time.monotonic()
        self.anchor_match = 0.0
        return self.match_time()

    def clock_update(self, now: float | None = None) -> dict[str, Any]:
        """Return the JSON payload published to the viewer for the current clock state."""
        return {
            "match_seconds": self.match_time(now),
            "speed": self.speed,
            "anchor": {
                "wall": self.anchor_wall,
                "match": self.anchor_match,
            },
        }


__all__ = ["SessionClock"]
