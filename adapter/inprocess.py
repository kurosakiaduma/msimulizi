"""In-process adapter that streams the synthetic generator output.

The generator is deterministic for a given storyline and seed, making it a good
replay source for local testing and demo sessions.
"""

from __future__ import annotations

import asyncio
from typing import AsyncIterator

from adapter.base import _event_to_seconds
from generator.generate import generate_match
from shared.models import Event


class InProcessAdapter:
    """Stream generated synthetic match events at the requested playback speed."""

    def __init__(self, storyline: str = "comeback_from_two_down", seed: int = 42) -> None:
        self.storyline = storyline
        self.seed = seed

    async def events(self, session_id: str, speed: float = 1.0) -> AsyncIterator[Event]:
        """Yield events from the in-process generator at the chosen speed."""
        if speed <= 0:
            raise ValueError("speed must be greater than zero")

        last_time = 0.0
        for event in generate_match(self.storyline, self.seed):
            match_time = _event_to_seconds(event)
            if last_time and match_time > last_time:
                await asyncio.sleep((match_time - last_time) / speed)
            last_time = match_time
            yield event


__all__ = ["InProcessAdapter"]
