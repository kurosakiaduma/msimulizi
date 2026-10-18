"""Tests for the synthetic match generator and validation script."""

from __future__ import annotations

from generator.generate import generate_match, make_match_id
from generator.validate import validate_storyline


def test_make_match_id_is_stable_and_slugged():
    """The generated match IDs should be deterministic and human-readable."""
    assert make_match_id("comeback from two down", 42) == "comeback-from-two-down-42"
    assert make_match_id("comeback_from_two_down", 42) == "comeback-from-two-down-42"


def test_generate_match_is_deterministic_for_same_seed_storyline():
    """A seeded storyline should reproduce an identical synthetic match."""
    first = list(generate_match("comeback_from_two_down", 7))
    second = list(generate_match("comeback_from_two_down", 7))
    third = list(generate_match("late_equaliser", 7))

    assert first == second
    assert first != third


def test_event_ids_use_match_id_then_sequence_number():
    """Each event ID should embed the match ID and an incrementing sequence."""
    events = list(generate_match("red_card_shift", 11))
    assert events[0].event_id.startswith("red-card-shift-11-")
    assert events[0].event_id.endswith("-000001")
    assert len({event.event_id for event in events}) == len(events)


def test_fictional_names_are_used_in_generated_events():
    """Generated names should remain fictional and free of real clubs or players."""
    events = list(generate_match("dominant_side_loses", 13))
    teams = {event.team for event in events if event.team not in {"match", "referee"}}
    assert teams
    assert all("Premier" not in team and "Manchester" not in team and "Arsenal" not in team for team in teams)
    assert all(" " in event.player for event in events if event.player not in {"match", "referee"})


def test_validation_rejects_out_of_band_stats():
    """Validation should fail when the summary statistics are clearly out of band."""
    bad_stats = {
        "total_shots": 999,
        "goals_home": 20,
        "goals_away": 20,
        "xg_home": 99.0,
        "xg_away": 99.0,
    }
    assert validate_storyline("comeback_from_two_down", seed=42, stats=bad_stats) is False
