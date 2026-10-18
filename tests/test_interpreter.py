"""Tests for the deterministic match-state interpreter."""

from __future__ import annotations

import pytest

from pipeline.interpreter import Interpreter
from shared.models import Event, EventType
from shared.pubsub import PubSub


def _make_event(
    *,
    event_id: str,
    match_id: str,
    minute: int,
    second: int,
    team: str,
    player: str,
    event_type: EventType,
    outcome: str | None = None,
    x_start: float = 50.0,
    y_start: float = 50.0,
    x_end: float | None = None,
    y_end: float | None = None,
    xg: float | None = None,
    pressure: bool = False,
    score_home: int = 0,
    score_away: int = 0,
    is_header: bool = False,
    is_penalty: bool = False,
) -> Event:
    """Create a compact synthetic event for interpreter tests."""
    return Event(
        event_id=event_id,
        match_id=match_id,
        period=1 if minute < 45 else 2,
        minute=minute,
        second=second,
        team=team,
        player=player,
        event_type=event_type,
        x_start=x_start,
        y_start=y_start,
        x_end=x_end,
        y_end=y_end,
        outcome=outcome,
        xg=xg,
        is_header=is_header,
        is_penalty=is_penalty,
        pressure=pressure,
        score_home=score_home,
        score_away=score_away,
    )


def test_interpreter_tracks_xg_and_pass_accuracy():
    """The interpreter should aggregate xG and player pass stats for each team."""
    bus = PubSub()
    interpreter = Interpreter("session-1", match_id="m-1", bus=bus)

    events = [
        _make_event(event_id="m-1-000001", match_id="m-1", minute=0, second=0, team="Home City", player="match", event_type=EventType.metadata),
        _make_event(event_id="m-1-000002", match_id="m-1", minute=7, second=12, team="Home City", player="Amina Okafor", event_type=EventType.pass_, outcome="success", x_start=30.0, y_start=50.0, x_end=55.0, y_end=48.0),
        _make_event(event_id="m-1-000003", match_id="m-1", minute=7, second=23, team="Home City", player="Amina Okafor", event_type=EventType.pass_, outcome="fail", x_start=50.0, y_start=48.0, x_end=45.0, y_end=49.0),
        _make_event(event_id="m-1-000004", match_id="m-1", minute=8, second=4, team="Home City", player="Amina Okafor", event_type=EventType.shot, outcome="goal", x_start=22.0, y_start=46.0, x_end=40.0, y_end=42.0, xg=0.41, pressure=True, score_home=1, score_away=0),
        _make_event(event_id="m-1-000005", match_id="m-1", minute=12, second=7, team="Away City", player="Kofi Nimo", event_type=EventType.pass_, outcome="success", x_start=70.0, y_start=52.0, x_end=55.0, y_end=48.0),
        _make_event(event_id="m-1-000006", match_id="m-1", minute=12, second=15, team="Away City", player="Kofi Nimo", event_type=EventType.shot, outcome="miss", x_start=18.0, y_start=48.0, x_end=35.0, y_end=46.0, xg=0.18, score_home=1, score_away=0),
    ]

    for event in events:
        interpreter.process_event(event)

    state = interpreter.state
    assert state.xg_home == pytest.approx(0.41)
    assert state.xg_away == pytest.approx(0.18)
    assert state.player_stats["Home City:Amina Okafor"].passes_attempted == 2
    assert state.player_stats["Home City:Amina Okafor"].passes_completed == 1
    assert bus.latest("match_state") == state


def test_interpreter_updates_momentum_and_pressure_windows():
    """The rolling window should lift the home side when it dominates recent events."""
    interpreter = Interpreter("session-2", match_id="m-2")

    home_events = [
        _make_event(event_id="m-2-000001", match_id="m-2", minute=8, second=0, team="Home City", player="Amina", event_type=EventType.pass_, outcome="success", x_start=22.0, y_start=50.0, x_end=55.0, y_end=48.0, pressure=True),
        _make_event(event_id="m-2-000002", match_id="m-2", minute=9, second=0, team="Home City", player="Amina", event_type=EventType.shot, outcome="goal", x_start=18.0, y_start=50.0, x_end=30.0, y_end=45.0, xg=0.55, pressure=True, score_home=1, score_away=0),
        _make_event(event_id="m-2-000003", match_id="m-2", minute=9, second=10, team="Away City", player="Kofi", event_type=EventType.pass_, outcome="success", x_start=70.0, y_start=50.0, x_end=50.0, y_end=48.0),
    ]

    for event in home_events:
        interpreter.process_event(event)

    state = interpreter.state
    assert state.pressure_rate_home > state.pressure_rate_away
    assert state.momentum_home > state.momentum_away
    assert state.tempo >= 0.0


def test_interpreter_maybe_snapshot_triggers_on_half_time():
    """A half-time or full-time event should trigger a snapshot opportunity."""
    interpreter = Interpreter("session-3", match_id="m-3")

    event = _make_event(
        event_id="m-3-000001",
        match_id="m-3",
        minute=45,
        second=0,
        team="match",
        player="referee",
        event_type=EventType.half_time,
        outcome="half_time",
    )

    snapshot = interpreter.maybe_snapshot(event)
    assert snapshot is not None
    assert snapshot.match_id == "m-3"
