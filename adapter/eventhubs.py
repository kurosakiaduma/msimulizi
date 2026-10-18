"""Minimal Event Hubs-style adapter with checkpointing.

This implementation intentionally avoids hard Azure dependencies and instead
streams a supplied event iterable while persisting a checkpoint so reconnects can
resume from the most recently delivered event.
"""

from __future__ import annotations

import asyncio
import json
from pathlib import Path
from typing import AsyncIterator, Iterable, Sequence

from adapter.base import _event_to_seconds
from shared.models import Event


class EventHubsAdapter:
    """A minimal checkpointed consumer that behaves like a live Event Hubs stream."""

    def __init__(
        self,
        events: Sequence[Event] | Iterable[Event] | None = None,
        *,
        checkpoint_dir: str | Path | None = None,
    ) -> None:
        self._events = list(events) if events is not None else []
        self._checkpoint_dir = Path(checkpoint_dir) if checkpoint_dir is not None else None

    def _checkpoint_path(self, session_id: str) -> Path:
        if self._checkpoint_dir is None:
            return Path(f".{session_id}.eventhubs.checkpoint.json")
        self._checkpoint_dir.mkdir(parents=True, exist_ok=True)
        return self._checkpoint_dir / f"{session_id}.json"

    def _load_checkpoint(self, session_id: str) -> str | None:
        checkpoint = self._checkpoint_path(session_id)
        if not checkpoint.exists():
            return None
        try:
            with checkpoint.open("r", encoding="utf-8") as handle:
                payload = json.load(handle)
        except (OSError, ValueError):
            return None
        return payload.get("last_event_id") if isinstance(payload, dict) else None

    def _save_checkpoint(self, session_id: str, event: Event) -> None:
        checkpoint = self._checkpoint_path(session_id)
        payload = {"last_event_id": event.event_id, "match_id": event.match_id}
        with checkpoint.open("w", encoding="utf-8") as handle:
            json.dump(payload, handle)

    async def events(self, session_id: str, speed: float = 1.0) -> AsyncIterator[Event]:
        """Yield events from the backing stream while checkpointing progress."""
        if speed <= 0:
            raise ValueError("speed must be greater than zero")

        checkpoint = self._load_checkpoint(session_id)
        last_time = 0.0
        for event in self._events:
            if checkpoint is not None:
                if event.event_id == checkpoint:
                    checkpoint = None
                    continue
                if checkpoint is not None:
                    continue

            match_time = _event_to_seconds(event)
            if last_time and match_time > last_time:
                await asyncio.sleep((match_time - last_time) / speed)
            last_time = match_time
            self._save_checkpoint(session_id, event)
            yield event


__all__ = ["EventHubsAdapter"]
