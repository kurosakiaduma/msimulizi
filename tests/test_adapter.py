"""Tests for the event source adapter selection and replay behavior."""

from __future__ import annotations

import asyncio
import json
import os
from pathlib import Path

from adapter.factory import get_adapter
from adapter.file_replay import FileReplayAdapter
from adapter.inprocess import InProcessAdapter
from generator.generate import generate_match
from shared.models import EventType


def test_inprocess_adapter_keeps_event_order_and_type():
    """The in-process adapter should mirror the synthetic generator stream."""

    async def _run() -> None:
        expected = list(generate_match("comeback_from_two_down", 7))
        adapter = InProcessAdapter("comeback_from_two_down", seed=7)
        actual = [event async for event in adapter.events("demo-session", speed=1_000_000.0)]

        assert [event.event_id for event in actual] == [event.event_id for event in expected]
        assert actual[0].event_type == EventType.metadata
        assert actual[-1].event_type == EventType.full_time

    asyncio.run(_run())


def test_factory_reads_event_source_env_var(tmp_path: Path):
    """Factory selection should follow the repository EVENT_SOURCE contract."""
    path = tmp_path / "events.jsonl"
    events = list(generate_match("late_equaliser", 9))[:3]
    with path.open("w", encoding="utf-8") as handle:
        for event in events:
            handle.write(json.dumps({
                "event_id": event.event_id,
                "match_id": event.match_id,
                "period": event.period,
                "minute": event.minute,
                "second": event.second,
                "team": event.team,
                "player": event.player,
                "event_type": event.event_type.value,
                "x_start": event.x_start,
                "y_start": event.y_start,
                "x_end": event.x_end,
                "y_end": event.y_end,
                "outcome": event.outcome,
                "xg": event.xg,
                "is_header": event.is_header,
                "is_penalty": event.is_penalty,
                "pressure": event.pressure,
                "score_home": event.score_home,
                "score_away": event.score_away,
            }))
            handle.write("\n")

    old = os.environ.get("EVENT_SOURCE")
    os.environ["EVENT_SOURCE"] = "file"
    try:
        adapter = get_adapter(path=str(path), checkpoint_dir=tmp_path / "checkpoint")
        assert isinstance(adapter, FileReplayAdapter)

        async def _collect() -> list[str]:
            return [event.event_id async for event in adapter.events("factory-check", speed=1_000_000.0)][:2]

        assert asyncio.run(_collect()) == [event.event_id for event in events[:2]]
    finally:
        if old is None:
            os.environ.pop("EVENT_SOURCE", None)
        else:
            os.environ["EVENT_SOURCE"] = old


def test_file_replay_resumes_after_disconnect(tmp_path: Path):
    """Checkpointed replays should resume from the last delivered event ID."""
    path = tmp_path / "resume.jsonl"
    events = list(generate_match("red_card_shift", 11))[:4]
    with path.open("w", encoding="utf-8") as handle:
        for event in events:
            payload = {
                "event_id": event.event_id,
                "match_id": event.match_id,
                "period": event.period,
                "minute": event.minute,
                "second": event.second,
                "team": event.team,
                "player": event.player,
                "event_type": event.event_type.value,
                "x_start": event.x_start,
                "y_start": event.y_start,
                "x_end": event.x_end,
                "y_end": event.y_end,
                "outcome": event.outcome,
                "xg": event.xg,
                "is_header": event.is_header,
                "is_penalty": event.is_penalty,
                "pressure": event.pressure,
                "score_home": event.score_home,
                "score_away": event.score_away,
            }
            handle.write(json.dumps(payload) + "\n")

    checkpoint_dir = tmp_path / "checkpoints"
    first = FileReplayAdapter(path=path, checkpoint_dir=checkpoint_dir)

    async def _run() -> None:
        stream = first.events("resume-session", speed=1_000_000.0)
        first_event = await anext(stream)
        second_event = await anext(stream)
        assert first_event.event_id == events[0].event_id
        assert second_event.event_id == events[1].event_id

        resumed = FileReplayAdapter(path=path, checkpoint_dir=checkpoint_dir)
        remaining = [event async for event in resumed.events("resume-session", speed=1_000_000.0)]
        assert [event.event_id for event in remaining] == [event.event_id for event in events[2:]]

    asyncio.run(_run())
