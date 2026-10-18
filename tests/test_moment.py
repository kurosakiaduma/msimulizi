"""Unit tests for the key-moment detector."""

from __future__ import annotations

from shared.models import Event, EventType, MatchState
from pipeline.moment import MomentAgent, detect_moment, detect_trigger_tags


def _match_state(**overrides) -> MatchState:
    """Build a minimal match-state instance for moment tests."""
    data = {
        "match_id": "match-01",
        "session_id": "session-01",
        "sequence_number": 1,
        "last_event_id": "match-01-000001",
        "minute": 0,
        "second": 0,
        "score_home": 0,
        "score_away": 0,
        "possession_home": 0.5,
        "field_tilt_home": 0.5,
        "field_tilt_away": 0.5,
        "xg_home": 0.0,
        "xg_away": 0.0,
        "momentum_home": 50.0,
        "momentum_away": 50.0,
        "pressure_rate_home": 0.0,
        "pressure_rate_away": 0.0,
        "tempo": 0.0,
        "player_stats": {},
    }
    data.update(overrides)
    return MatchState(**data)


def _event(**overrides) -> Event:
    """Build a minimal event instance for moment tests."""
    data = {
        "event_id": "match-01-000001",
        "match_id": "match-01",
        "period": 1,
        "minute": 0,
        "second": 0,
        "team": "Home",
        "player": "Alpha",
        "event_type": EventType.goal,
        "x_start": 0.0,
        "y_start": 0.0,
        "x_end": 0.0,
        "y_end": 0.0,
        "outcome": "success",
        "xg": 0.0,
        "is_header": False,
        "is_penalty": False,
        "pressure": False,
        "score_home": 1,
        "score_away": 0,
    }
    data.update(overrides)
    return Event(**data)


def test_goal_and_late_game_tags_merge_to_rank_one():
    """A goal in the final 15 minutes should keep the highest urgency without raising above rank 1."""
    state = _match_state(minute=80, score_home=1, score_away=0, momentum_home=51.0, momentum_away=49.0)
    event = _event(minute=80, second=12, team="Home", player="Alpha", event_type=EventType.goal, score_home=2, score_away=0)

    moment = detect_moment(state, event)
    assert moment is not None
    assert "goal" in moment.trigger_tags
    assert "late_game" in moment.trigger_tags
    assert moment.priority_rank == 1
    assert moment.moment_id == "match-01-km-0001"


def test_red_card_rank_is_priority_one_and_full_time_signal_is_emitted():
    """Red cards are treated as the top-urgency key moments, and full-time can emit a recap signal."""
    state = _match_state(minute=88, score_home=1, score_away=1, momentum_home=50.0, momentum_away=50.0)
    event = _event(minute=88, second=45, team="Away", player="Bravo", event_type=EventType.card, outcome="red", score_home=1, score_away=1)

    moment = MomentAgent(match_id="match-01").detect(state, event)
    assert moment is not None
    assert "red_card" in moment.trigger_tags
    assert moment.priority_rank == 1

    full_time = _event(event_id="match-01-000010", minute=90, second=0, event_type=EventType.full_time, team="match", player="referee", outcome=None, score_home=2, score_away=1)
    full_time_moment = MomentAgent(match_id="match-01").detect(state, full_time)
    assert full_time_moment is not None
    assert "full_time" in full_time_moment.trigger_tags


def test_momentum_swing_cooldown_prevents_duplicate_triggering():
    """Momentum swing should fire once per 10-minute window and remain suppressed inside the cooldown."""
    agent = MomentAgent(match_id="match-99")
    state_one = _match_state(match_id="match-99", minute=12, momentum_home=70.0, momentum_away=45.0)
    event_one = _event(match_id="match-99", event_id="match-99-000001", minute=12, second=10, team="Home", player="Alpha", event_type=EventType.pass_, xg=0.0, outcome="success", score_home=0, score_away=0)
    first = agent.detect(state_one, event_one)
    assert first is None

    state_two = _match_state(match_id="match-99", minute=12, momentum_home=84.0, momentum_away=40.0)
    event_two = _event(match_id="match-99", event_id="match-99-000002", minute=12, second=23, team="Home", player="Alpha", event_type=EventType.shot, xg=0.60, outcome="off_target", score_home=0, score_away=0)
    second = agent.detect(state_two, event_two)
    assert second is not None
    assert "momentum_swing" in second.trigger_tags

    state_three = _match_state(match_id="match-99", minute=15, momentum_home=78.0, momentum_away=46.0)
    event_three = _event(match_id="match-99", event_id="match-99-000003", minute=15, second=5, team="Home", player="Alpha", event_type=EventType.pass_, xg=0.0, outcome="success", score_home=0, score_away=0)
    third = agent.detect(state_three, event_three)
    assert third is None


def test_detect_trigger_tags_are_stable_and_deterministic():
    """The tag detector should generate identical tags for the same state and event."""
    state = _match_state(minute=79, score_home=2, score_away=1, momentum_home=60.0, momentum_away=40.0)
    event = _event(minute=79, second=44, team="Home", player="Alpha", event_type=EventType.shot, xg=0.45, outcome="off_target", score_home=3, score_away=1)

    first = detect_trigger_tags(state, event)
    second = detect_trigger_tags(state, event)
    assert first == second
    assert "big_chance" in first
    assert "late_game" in first
