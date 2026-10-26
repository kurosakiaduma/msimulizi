"""JSONL replay source for synthetic match events.

This adapter reads one event per line from a JSONL file, replays it at a
playback multiplier, and persists the last delivered event ID in a checkpoint
file so reconnects resume from the correct point.
"""

from __future__ import annotations

import asyncio
import json
from pathlib import Path
from typing import Any, AsyncIterator, Iterable

from adapter.base import _event_to_seconds
from shared.models import Event, EventType


class FileReplayAdapter:
    """Replay a persisted JSONL event stream with optional checkpoint resume."""

    def __init__(
        self,
        path: str | Path | None = None,
        *,
        checkpoint_dir: str | Path | None = None,
        events: Iterable[Event | dict[str, Any]] | None = None,
    ) -> None:
        self._path = Path(path) if path is not None else None
        self._checkpoint_dir = Path(checkpoint_dir) if checkpoint_dir is not None else None
        self._events = list(events) if events is not None else self._load_events_from_file()

    def _load_events_from_file(self) -> list[Event]:
        if self._path is None:
            return []
        if not self._path.exists():
            return []

        items: list[Event] = []
        with self._path.open("r", encoding="utf-8") as handle:
            for line in handle:
                line = line.strip()
                if not line:
                    continue
                payload = json.loads(line)
                items.append(_decode_event(payload))
        return items

    def _checkpoint_path(self, session_id: str) -> Path:
        if self._checkpoint_dir is None:
            return Path(f".{session_id}.checkpoint.json")
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
        """Yield replayed events in order, replaying at the given speed multiplier."""
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


def _decode_event(payload: dict[str, Any]) -> Event:
    """Convert a JSON object into an Event dataclass instance."""
    event_type = payload.get("event_type")
    if isinstance(event_type, str):
        event_type_value = EventType(event_type)
    else:
        event_type_value = EventType.metadata
    return Event(
        event_id=str(payload.get("event_id", "unknown-000001")),
        match_id=str(payload.get("match_id", "synthetic-match")),
        period=int(payload.get("period", 1)),
        minute=int(payload.get("minute", 0)),
        second=int(payload.get("second", 0)),
        team=str(payload.get("team", "unknown")),
        player=str(payload.get("player", "unknown")),
        event_type=event_type_value,
        x_start=float(payload.get("x_start", 0.0)),
        y_start=float(payload.get("y_start", 0.0)),
        x_end=float(payload.get("x_end", 0.0)) if payload.get("x_end") is not None else None,
        y_end=float(payload.get("y_end", 0.0)) if payload.get("y_end") is not None else None,
        outcome=payload.get("outcome"),
        xg=float(payload.get("xg")) if payload.get("xg") is not None else None,
        is_header=bool(payload.get("is_header", False)),
        is_penalty=bool(payload.get("is_penalty", False)),
        pressure=bool(payload.get("pressure", False)),
        score_home=int(payload.get("score_home", 0)),
        score_away=int(payload.get("score_away", 0)),
    )


__all__ = ["FileReplayAdapter"]
