"""Tests covering the Personaliser Agent route, spotlight, and metric-focus logic."""

from __future__ import annotations

from pipeline.personaliser import PersonaliserAgent, apply_metric_focus, derive_club_perspective
from shared.models import Event, EventType, KeyMoment


def make_event(**overrides):
    payload = {
        "event_id": "match-001-000010",
        "match_id": "match-001",
        "period": 1,
        "minute": 12,
        "second": 30,
        "team": "Ngome United",
        "player": "Amina Kivuva",
        "event_type": EventType.goal,
        "x_start": 40.0,
        "y_start": 50.0,
        "x_end": None,
        "y_end": None,
        "outcome": "success",
        "xg": 0.45,
        "is_header": False,
        "is_penalty": False,
        "pressure": False,
        "score_home": 1,
        "score_away": 0,
    }
    payload.update(overrides)
    return Event(**payload)


class TestPersonaliserAgent:
    def test_club_perspective_is_derived_from_favourite_club(self):
        agent = PersonaliserAgent(favourite_club="Ngome United")

        assert agent.derive_club_perspective("Ngome United") == "home"
        assert agent.derive_club_perspective("Pwani Athletic") == "away"
        assert derive_club_perspective("Pwani Athletic", favourite_club="Ngome United") == "away"

    def test_profile_update_changes_subsequent_profile_keys(self):
        agent = PersonaliserAgent(favourite_club="Ngome United", language="sw", mode="casual")

        key_one = agent.derive_profile_key("match-001", team="Ngome United")
        agent.update_profile(favourite_club="Pwani Athletic", language="en", mode="analyst")
        key_two = agent.derive_profile_key("match-001", team="Pwani Athletic")

        assert key_one == "match-001.sw.casual.home"
        assert key_two == "match-001.en.analyst.home"

    def test_cache_miss_builds_narration_request(self):
        agent = PersonaliserAgent(favourite_club="Ngome United", language="sw", mode="casual", narration_cache={})
        moment = KeyMoment(
            moment_id="match-001-km-0001",
            match_id="match-001",
            trigger_event_id="match-001-000010",
            trigger_tags=["goal"],
            priority_rank=1,
            minute=12,
            second=30,
        )

        request = agent.prepare_key_moment(moment, event=make_event(team="Ngome United", player="Amina Kivuva"))

        assert request is not None
        assert request.profile_key == "match-001.sw.casual.home"
        assert request.player == "Amina Kivuva"

    def test_goal_assist_and_tackle_won_are_detected(self):
        agent = PersonaliserAgent(favourite_player="Maya Njeri")
        pass_event = make_event(
            event_id="match-001-000010",
            minute=68,
            second=4,
            team="Ngome United",
            player="Maya Njeri",
            event_type=EventType.pass_,
            outcome="success",
            xg=None,
            score_home=1,
            score_away=1,
        )
        goal_event = make_event(
            event_id="match-001-000011",
            minute=68,
            second=9,
            team="Ngome United",
            player="Amina Kivuva",
            event_type=EventType.goal,
            outcome="success",
            score_home=2,
            score_away=1,
        )
        tackle_event = make_event(
            event_id="match-001-000012",
            minute=71,
            second=12,
            team="Ngome United",
            player="Maya Njeri",
            event_type=EventType.tackle,
            outcome="success",
            xg=None,
            score_home=2,
            score_away=1,
        )

        assert agent.evaluate_spotlight(goal_event, recent_events=[pass_event]).reason == "assist"
        assert agent.evaluate_spotlight(tackle_event, recent_events=[goal_event]).reason == "tackle_won"

    def test_spotlight_spacing_blocks_repeats_within_three_minutes(self):
        agent = PersonaliserAgent(favourite_player="Amina Kivuva")
        first = make_event(event_id="match-001-000020", minute=80, second=0, event_type=EventType.shot, player="Amina Kivuva", outcome="success")
        second = make_event(event_id="match-001-000021", minute=82, second=30, event_type=EventType.shot, player="Amina Kivuva", outcome="success")

        assert agent.evaluate_spotlight(first) is not None
        assert agent.evaluate_spotlight(second) is None

    def test_metric_focus_drops_rank_4_and_5_without_metric_and_preserves_rank_1(self):
        rank1 = KeyMoment(moment_id="m1", match_id="match-001", trigger_event_id="e1", trigger_tags=["goal"], priority_rank=1, minute=10, second=5)
        rank4 = KeyMoment(moment_id="m2", match_id="match-001", trigger_event_id="e2", trigger_tags=["player_milestone"], priority_rank=4, minute=20, second=5)
        rank2 = KeyMoment(moment_id="m3", match_id="match-001", trigger_event_id="e3", trigger_tags=["big_chance"], priority_rank=2, minute=30, second=5)

        assert apply_metric_focus(rank1, has_metric=False) == (True, 1, 6000)
        assert apply_metric_focus(rank4, has_metric=False) == (False, 4, 0)
        assert apply_metric_focus(rank2, has_metric=True) == (True, 2, 3000)
