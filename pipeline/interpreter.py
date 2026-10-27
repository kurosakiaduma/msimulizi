"""Deterministic match-state interpreter for the Msimulizi pipeline.

The interpreter consumes each event in a replay or live stream, updates the
session-scoped ``MatchState`` in memory, and publishes the new aggregate to the
shared pub/sub bus. It also records rolling metrics for possession, pressure,
field tilt, xG, momentum, and tempo.
"""

from __future__ import annotations

import asyncio
import math
from collections import defaultdict, deque
from datetime import UTC, datetime
from typing import Any, Deque

from shared.models import Event, EventType, MatchState, PlayerStats
from shared.pubsub import PubSub
from shared.xg import compute_xg


class Interpreter:
    """Deterministic match-state interpreter for one replay session."""

    def __init__(
        self,
        session_id: str,
        match_id: str | None = None,
        *,
        bus: PubSub | None = None,
    ) -> None:
        self.session_id = session_id
        self.match_id = match_id or "synthetic-match"
        self.bus = bus or PubSub()
        self.state = self._new_state()
        self._home_team: str | None = None
        self._away_team: str | None = None
        self._event_history: Deque[Event] = deque(maxlen=500)
        self._team_events: dict[str, list[Event]] = defaultdict(list)

    @property
    def home_team(self) -> str | None:
        """Canonical home-team label learned from the event stream."""
        return self._home_team

    @property
    def away_team(self) -> str | None:
        """Canonical away-team label learned from the event stream."""
        return self._away_team

    def _new_state(self) -> MatchState:
        """Instantiate the initial in-memory match aggregate for this session."""
        return MatchState(
            match_id=self.match_id,
            session_id=self.session_id,
            sequence_number=0,
            last_event_id="",
            minute=0,
            second=0,
            score_home=0,
            score_away=0,
            possession_home=0.5,
            field_tilt_home=0.5,
            field_tilt_away=0.5,
            xg_home=0.0,
            xg_away=0.0,
            momentum_home=50.0,
            momentum_away=50.0,
            pressure_rate_home=0.0,
            pressure_rate_away=0.0,
            tempo=0.0,
            player_stats={},
            updated_at=datetime.now(UTC),
        )

    def _coerce_event(self, event: Event | dict[str, Any]) -> Event:
        """Accept either a dataclass event or a dictionary payload."""
        if isinstance(event, Event):
            return event

        x_start_value = event.get("x_start")
        y_start_value = event.get("y_start")
        x_end_value = event.get("x_end")
        y_end_value = event.get("y_end")
        xg_value = event.get("xg")

        return Event(
            event_id=str(event.get("event_id", f"{self.match_id}-000000")),
            match_id=str(event.get("match_id", self.match_id)),
            period=int(event.get("period", 1)),
            minute=int(event.get("minute", 0)),
            second=int(event.get("second", 0)),
            team=str(event.get("team", "unknown")),
            player=str(event.get("player", "unknown")),
            event_type=EventType(event.get("event_type", EventType.metadata.value)),
            x_start=float(x_start_value) if x_start_value is not None else 0.0,
            y_start=float(y_start_value) if y_start_value is not None else 0.0,
            x_end=float(x_end_value) if x_end_value is not None else None,
            y_end=float(y_end_value) if y_end_value is not None else None,
            outcome=event.get("outcome"),
            xg=float(xg_value) if xg_value is not None else None,
            is_header=bool(event.get("is_header", False)),
            is_penalty=bool(event.get("is_penalty", False)),
            pressure=bool(event.get("pressure", False)),
            score_home=int(event.get("score_home", 0)),
            score_away=int(event.get("score_away", 0)),
        )

    def _team_side(self, team: str) -> str:
        """Map a team label to the home or away side for this session."""
        if self._home_team is None:
            return "home"
        if team == self._home_team:
            return "home"
        if self._away_team is None or team == self._away_team:
            return "away"
        return "away"

    def _ensure_team_names(self, team: str) -> None:
        """Learn the home/away aliases cheaply from the first distinct teams seen."""
        if team in {"match", "referee"} or not team:
            return
        if self._home_team is None:
            self._home_team = team
            return
        if self._away_team is None and team != self._home_team:
            self._away_team = team

    def _team_is_home(self, team: str) -> bool:
        """Return whether a team label maps to the home side for this session."""
        if self._home_team is None:
            return True
        return team == self._home_team

    def _player_stats_for(self, player_name: str, team: str) -> PlayerStats:
        """Return the per-player aggregate, creating it when first seen."""
        key = f"{team}:{player_name}"
        entry = self.state.player_stats.get(key)
        if entry is None:
            entry = PlayerStats(player=player_name, team=team)
            self.state.player_stats[key] = entry
        return entry

    def _update_player_stats(self, event: Event) -> None:
        """Update per-player pass, shot, and pressure totals."""
        if not event.player or event.player in {"match", "referee"}:
            return

        stats = self._player_stats_for(event.player, event.team)
        if event.event_type == EventType.pass_:
            stats.passes_attempted += 1
            if event.outcome == "success":
                stats.passes_completed += 1
                if (
                    event.x_start is not None
                    and event.y_start is not None
                    and event.x_end is not None
                    and event.y_end is not None
                ):
                    distance = math.hypot(event.x_end - event.x_start, event.y_end - event.y_start)
                    stats.pass_distance_total += distance
        elif event.event_type == EventType.shot:
            stats.shots += 1
            if event.xg is not None:
                stats.xg_total += float(event.xg)
            if event.outcome == "goal":
                stats.goals += 1
                stats.shots_on_target += 1
        elif event.event_type == EventType.tackle:
            stats.tackles_attempted += 1
            if event.outcome == "success":
                stats.tackles_won += 1
        elif event.event_type == EventType.interception:
            stats.interceptions += 1
        elif event.event_type in {EventType.card, EventType.foul}:
            stats.cards += 1

    def _window_events(self, minutes: int) -> list[Event]:
        """Return the events within the requested trailing match-time window."""
        if not self._event_history:
            return []
        cutoff = max(0, self.state.minute - minutes)
        return [item for item in self._event_history if item.minute >= cutoff]

    def _event_contribution(self, event: Event) -> float:
        """Convert one event into the momentum-score raw contribution."""
        total = 0.0
        if event.event_type == EventType.shot:
            total += 2.0
        if event.xg is not None:
            total += float(event.xg) * 10.0
        if event.pressure:
            total += 1.0
        if event.event_type == EventType.pass_ and event.outcome == "success":
            total += 0.5
        return total

    def _compute_momentum(self) -> tuple[float, float]:
        """Return the current momentum scores for home and away teams."""
        events = self._window_events(10)
        home_raw = 0.0
        away_raw = 0.0
        for event in events:
            if self._team_is_home(event.team):
                home_raw += self._event_contribution(event)
            else:
                away_raw += self._event_contribution(event)
        home_score = max(0.0, min(100.0, 50.0 + home_raw - away_raw))
        away_score = max(0.0, min(100.0, 50.0 + away_raw - home_raw))
        return home_score, away_score

    def _update_window_metrics(self) -> None:
        """Update rolling pressure-rate, tempo, and momentum values."""
        window_5 = self._window_events(5)
        pressure_home = sum(
            1 for event in window_5 if event.pressure and self._team_is_home(event.team)
        )
        pressure_away = sum(
            1 for event in window_5 if event.pressure and not self._team_is_home(event.team)
        )

        self.state.pressure_rate_home = pressure_home / 5.0
        self.state.pressure_rate_away = pressure_away / 5.0
        self.state.tempo = max(0.0, len(window_5) / 5.0)
        self.state.momentum_home, self.state.momentum_away = self._compute_momentum()

    def _update_field_tilt(self, event: Event) -> None:
        """Track field tilt using final-third entries and possession share."""
        if event.event_type not in {EventType.pass_, EventType.carry, EventType.dribble}:
            return

        if event.x_end is not None and event.y_end is not None:
            final_third = event.x_end >= 66.0 and 15.0 <= event.y_end <= 85.0
            if final_third and event.outcome != "fail":
                if self._team_is_home(event.team):
                    self.state.field_tilt_home += 0.05
                else:
                    self.state.field_tilt_away += 0.05

        home_events = sum(
            1
            for past in self._window_events(10)
            if past.event_type in {EventType.pass_, EventType.carry, EventType.dribble}
            and self._team_is_home(past.team)
        )
        away_events = sum(
            1
            for past in self._window_events(10)
            if past.event_type in {EventType.pass_, EventType.carry, EventType.dribble}
            and not self._team_is_home(past.team)
        )
        total = home_events + away_events
        if total:
            # Laplace smoothing keeps the first few passes from displaying as
            # 100% / 0%. Early in a move that looks broken rather than merely
            # small-sample. As the window fills, the observed share dominates.
            self.state.possession_home = (home_events + 1) / (total + 2)
            self.state.field_tilt_home = (home_events + 1) / (total + 2)
            self.state.field_tilt_away = (away_events + 1) / (total + 2)

    def _update_xg(self, event: Event) -> None:
        """Accumulate team xG from all shot events seen so far."""
        if event.event_type != EventType.shot:
            return
        if event.xg is None:
            try:
                distance = max(0.0, abs(event.x_start - 50.0) + float(event.x_end or 0.0))
                angle = max(0.0, min(math.pi, abs(float(event.x_end or 0.0) - event.x_start) / 100.0 + 0.25))
                event.xg = compute_xg(
                    distance=distance,
                    angle=angle,
                    is_header=bool(event.is_header),
                    is_penalty=bool(event.is_penalty),
                )
            except Exception:
                return
        if self._team_is_home(event.team):
            self.state.xg_home += float(event.xg)
        else:
            self.state.xg_away += float(event.xg)

    def _publish_state(self) -> None:
        """Publish the current aggregate to the bus for MCP and live UI readers."""
        if self.bus is None:
            return
        payload = self.state
        try:
            loop = asyncio.get_running_loop()
        except RuntimeError:
            try:
                asyncio.run(self.bus.publish("match_state", payload))
                asyncio.run(self.bus.publish(f"match_state:{self.session_id}", payload))
            except RuntimeError:
                return
            return

        loop.create_task(self.bus.publish("match_state", payload))
        loop.create_task(self.bus.publish(f"match_state:{self.session_id}", payload))

    def _snapshot_needed(self, event: Event) -> bool:
        """Return whether this event should trigger a snapshot flush."""
        if event.event_type in {EventType.half_time, EventType.full_time}:
            return True
        if event.minute % 2 == 0 and event.minute > 0:
            return True
        return False

    def snapshot(self) -> MatchState:
        """Return the current state for downstream snapshot consumers."""
        self.state.updated_at = datetime.now(UTC)
        return self.state

    def maybe_snapshot(self, event: Event, *, repo: Any | None = None) -> MatchState | None:
        """Persist a snapshot if the event warrants it."""
        if not self._snapshot_needed(event):
            return None
        state = self.snapshot()
        if repo is not None and hasattr(repo, "upsert"):
            try:
                import asyncio
                asyncio.run(
                    repo.upsert(
                        {
                            "id": f"{self.state.match_id}:{self.state.sequence_number}",
                            "match_id": self.state.match_id,
                            **state.__dict__,
                        }
                    )
                )
            except RuntimeError:
                pass
        return state

    def process_event(self, event: Event | dict[str, Any]) -> MatchState:
        """Consume a single event and update the rolling match state."""
        event = self._coerce_event(event)
        self.match_id = event.match_id or self.match_id
        self.state.match_id = self.match_id
        self._ensure_team_names(event.team)

        self.state.sequence_number += 1
        self.state.last_event_id = event.event_id
        self.state.minute = max(self.state.minute, event.minute)
        self.state.second = event.second
        self.state.score_home = int(event.score_home)
        self.state.score_away = int(event.score_away)

        self._event_history.append(event)
        self._update_player_stats(event)

        if event.event_type == EventType.shot:
            self._update_xg(event)

        if event.event_type in {EventType.goal, EventType.shot}:
            self.state.score_home = int(event.score_home)
            self.state.score_away = int(event.score_away)

        self._update_field_tilt(event)
        self._update_window_metrics()
        self.state.updated_at = datetime.now(UTC)

        self._publish_state()
        self.maybe_snapshot(event)
        return self.state

    def handle_event(self, event: Event | dict[str, Any]) -> MatchState:
        """Compatibility wrapper for event consumers that prefer a direct method name."""
        return self.process_event(event)

    def consume(self, event: Event | dict[str, Any]) -> MatchState:
        """Alias used by orchestration code and tests."""
        return self.process_event(event)

    def update(self, event: Event | dict[str, Any]) -> MatchState:
        """Alias for incremental state updates."""
        return self.process_event(event)

    def __call__(self, event: Event | dict[str, Any]) -> MatchState:
        """Allow the interpreter to be used like a callback."""
        return self.process_event(event)


MatchStateInterpreter = Interpreter

__all__ = ["Interpreter", "MatchStateInterpreter"]
