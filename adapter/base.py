"""Protocol and helpers for the replay and live event adapters.

The project uses a swappable event source so the same interpretation pipeline can
read from a local JSONL replay, an in-process generator, or a minimal Event
Hubs-style consumer without changing the rest of the agents.
"""

from __future__ import annotations

from typing import Any, AsyncIterator, Protocol

from shared.models import Event


class EventSourceAdapter(Protocol):
    """Protocol implemented by all event source adapters.

    Each adapter is session-scoped: callers provide a session_id and a speed
    multiplier, then iterate over the resulting event stream. Implementations
    typically implement this as an "async def" async-generator that yields
    Event objects; statically the method is declared synchronously as returning
    an AsyncIterator so type checkers accept async-generator implementations.
    """

    def events(self, session_id: str, speed: float = 1.0) -> AsyncIterator[Event]:
        """Return an async iterator yielding events for a replay or live session
        at the given playback speed."""
        ...


def _event_to_seconds(event: Event | dict[str, Any]) -> float:
    """Convert a match event into a wall-clock-like match-seconds value."""
    if isinstance(event, dict):
        minute = int(event.get("minute", 0))
        second = int(event.get("second", 0))
    else:
        minute = int(event.minute)
        second = int(event.second)
    return float(minute * 60 + second)


__all__ = ["EventSourceAdapter", "_event_to_seconds"]
