"""Factory for selecting the configured event source adapter.

The project design allows three source modes: file replay, in-process replay,
and a live Event Hubs-style stream. This module resolves the active mode from the
environment and returns an adapter instance configured for that mode.
"""

from __future__ import annotations

import os
from typing import Any

from adapter.base import EventSourceAdapter
from adapter.eventhubs import EventHubsAdapter
from adapter.file_replay import FileReplayAdapter
from adapter.inprocess import InProcessAdapter


def get_adapter(*, source: str | None = None, **kwargs: Any) -> EventSourceAdapter:
    """Return the configured adapter based on the source mode."""
    source_name = (source or os.getenv("EVENT_SOURCE") or "inprocess").lower()

    if source_name == "file":
        path = kwargs.get("path") or kwargs.get("file_path")
        checkpoint_dir = kwargs.get("checkpoint_dir")
        events = kwargs.get("events")
        return FileReplayAdapter(path=path, checkpoint_dir=checkpoint_dir, events=events)

    if source_name == "eventhubs":
        checkpoint_dir = kwargs.get("checkpoint_dir")
        events = kwargs.get("events")
        return EventHubsAdapter(events=events, checkpoint_dir=checkpoint_dir)

    if source_name == "inprocess":
        storyline = kwargs.get("storyline", "comeback_from_two_down")
        seed = int(kwargs.get("seed", 42))
        return InProcessAdapter(storyline=storyline, seed=seed)

    raise ValueError(f"Unsupported event source: {source_name}")


__all__ = ["get_adapter"]
