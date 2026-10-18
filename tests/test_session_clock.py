"""Tests for the per-session replay clock."""

from __future__ import annotations

from shared.session_clock import SessionClock


def test_match_time_tracks_speed(monkeypatch):
    """A speed-adjusted clock should advance in match seconds at the configured rate."""
    start = 1_000.0
    clock = SessionClock(anchor_wall=start, anchor_match=15.0, speed=2.0)

    monkeypatch.setattr("shared.session_clock.time.monotonic", lambda: start + 1.0)
    assert clock.match_time() == 17.0

    monkeypatch.setattr("shared.session_clock.time.monotonic", lambda: start + 2.5)
    assert clock.match_time() == 20.0


def test_update_reanchors_without_jump(monkeypatch):
    """Changing speed should preserve the current match position across the re-anchor."""
    start = 2_000.0
    clock = SessionClock(anchor_wall=start, anchor_match=90.0, speed=1.0)

    monkeypatch.setattr("shared.session_clock.time.monotonic", lambda: start + 2.0)
    before = clock.match_time()
    assert before == 92.0

    monkeypatch.setattr("shared.session_clock.time.monotonic", lambda: start + 3.0)
    updated = clock.update(4.0)
    assert updated == 93.0
    assert clock.speed == 4.0
    assert clock.anchor_match == 93.0

    monkeypatch.setattr("shared.session_clock.time.monotonic", lambda: start + 4.0)
    assert clock.match_time() == 97.0


def test_restart_reanchors_to_zero(monkeypatch):
    """Restarting should reset the timebase while keeping the current speed."""
    start = 5_000.0
    clock = SessionClock(anchor_wall=start, anchor_match=42.0, speed=1.5)

    monkeypatch.setattr("shared.session_clock.time.monotonic", lambda: start + 2.0)
    restarted = clock.restart()
    assert restarted == 0.0
    assert clock.anchor_match == 0.0
    assert clock.speed == 1.5


def test_clock_update_and_lookahead_follow_speed(monkeypatch):
    """The message payload and the lookahead window should reflect the current speed."""
    start = 10_000.0
    clock = SessionClock(anchor_wall=start, anchor_match=30.0, speed=0.1)

    monkeypatch.setattr("shared.session_clock.time.monotonic", lambda: start + 0.0)
    assert clock.match_time() == 30.0
    assert clock.lookahead_limit() == 31.0
    assert clock.clock_update()["match_seconds"] == 30.0

    clock.update(1.0)
    assert clock.lookahead_limit() == 40.0

    monkeypatch.setattr("shared.session_clock.time.monotonic", lambda: start + 0.0)
    clock.update(4.0)
    assert clock.lookahead_limit() == 70.0

    clock.restart()
    assert clock.clock_update()["match_seconds"] == 0.0
    assert clock.clock_update()["speed"] == 4.0
