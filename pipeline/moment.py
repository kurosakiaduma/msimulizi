"""Moment detection and priority ranking for the Msimulizi pipeline.

The moment agent consumes the most recent match state and an event, identifies
any trigger tags relevant to that event, and emits a single ``KeyMoment`` object
when one or more rules fire. The result is deterministic and stable across runs
because the priority config is loaded from a YAML file and the event sequence is
per match.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

import yaml

from shared.models import Event, EventType, KeyMoment, MatchState

_DEFAULT_CONFIG_PATH = Path(__file__).resolve().parents[1] / "moments" / "priority_config.yaml"


def _normalise_trigger_name(name: str) -> str:
    """Normalise a trigger name so YAML keys and runtime names stay consistent."""
    return str(name).strip().lower().replace("-", "_").replace(" ", "_")


def load_priority_config(config_path: str | Path | None = None) -> tuple[dict[str, int], float]:
    """Load the YAML priority config and coerce it into the runtime mapping."""
    path = Path(config_path) if config_path is not None else _DEFAULT_CONFIG_PATH
    ranks: dict[str, int] = {}
    xg_threshold = 0.40

    if path.exists():
        with path.open("r", encoding="utf-8") as handle:
            loaded = yaml.safe_load(handle) or {}
        if isinstance(loaded, dict):
            xg_threshold = float(loaded.get("xg_threshold", xg_threshold))
            direct = loaded.get("priority_ranks", loaded)
            if isinstance(direct, dict):
                for raw_key, raw_value in direct.items():
                    if raw_key in {"xg_threshold", "priority_ranks"}:
                        continue
                    ranks[_normalise_trigger_name(str(raw_key))] = int(raw_value)

    for key, default_value in {
        "goal": 1,
        "red_card": 1,
        "big_chance": 2,
        "lead_change": 2,
        "momentum_swing": 3,
        "player_milestone": 4,
        "full_time": 5,
        "late_game": 0,
    }.items():
        ranks.setdefault(key, default_value)

    return ranks, float(xg_threshold)


def _coerce_event(event: Event | dict[str, Any]) -> Event:
    """Normalise a dataclass or dictionary-backed event to a typed ``Event`` instance."""
    if isinstance(event, Event):
        return event
    payload = dict(event)
    event_type = payload.get("event_type")
    if event_type is not None and not isinstance(event_type, EventType):
        payload["event_type"] = EventType(str(event_type))
    return Event(**payload)


def detect_trigger_tags(match_state: MatchState, event: Event | dict[str, Any], *, config_path: str | Path | None = None) -> list[str]:
    """Return all trigger tags that apply to a single match event."""
    event_obj = _coerce_event(event)
    tags: list[str] = []
    seen: set[str] = set()

    def add(tag: str) -> None:
        normalised = _normalise_trigger_name(tag)
        if normalised and normalised not in seen:
            tags.append(normalised)
            seen.add(normalised)

    if event_obj.event_type == EventType.goal:
        add("goal")

    if event_obj.event_type == EventType.card:
        outcome = str(event_obj.outcome or "").lower().replace(" ", "_")
        if "red" in outcome or outcome in {"send_off", "dismissal", "red_card"}:
            add("red_card")

    if event_obj.event_type == EventType.shot:
        xg_value = float(event_obj.xg or 0.0)
        threshold = load_priority_config(config_path)[1]
        if xg_value >= threshold:
            add("big_chance")

    current_home = int(event_obj.score_home)
    current_away = int(event_obj.score_away)
    previous_home = int(match_state.score_home)
    previous_away = int(match_state.score_away)
    previous_leader = None
    if previous_home > previous_away:
        previous_leader = "home"
    elif previous_away > previous_home:
        previous_leader = "away"
    current_leader = None
    if current_home > current_away:
        current_leader = "home"
    elif current_away > current_home:
        current_leader = "away"
    if previous_leader != current_leader and current_leader is not None:
        add("lead_change")

    if event_obj.minute >= 75 or match_state.minute >= 75:
        add("late_game")

    if event_obj.event_type == EventType.full_time:
        add("full_time")

    if event_obj.event_type in {EventType.goal, EventType.shot, EventType.pass_, EventType.card, EventType.tackle, EventType.interception}:
        player_key = f"{event_obj.team}:{event_obj.player}"
        stats = match_state.player_stats.get(player_key)
        if stats is not None:
            if stats.goals >= 1 or stats.shots >= 3 or stats.passes_completed >= 10:
                add("player_milestone")

    return tags


def priority_for_tags(tags: list[str], *, config_path: str | Path | None = None) -> int:
    """Convert one or more trigger tags into a single priority rank."""
    ranks, _ = load_priority_config(config_path)
    if not tags:
        return 0
    base_rank = min(ranks.get(_normalise_trigger_name(tag), 5) for tag in tags)
    if "late_game" in {_normalise_trigger_name(tag) for tag in tags}:
        base_rank = max(1, base_rank + 1)
    return int(base_rank)


class MomentAgent:
    """Deterministic moment detector for one session or match stream."""

    def __init__(self, match_id: str | None = None, *, session_id: str | None = None, config_path: str | Path | None = None) -> None:
        self.match_id = match_id or "synthetic-match"
        self.session_id = session_id or "session"
        self.config_path = config_path
        self._priority_ranks, self._xg_threshold = load_priority_config(config_path)
        self._moment_sequence: dict[str, int] = {}
        self._last_swing_minute: dict[str, int] = {}
        self._last_delta: dict[str, float] = {}

    def _sequence_for(self, match_id: str) -> int:
        """Return the next monotonic Key Moment sequence for a match ID."""
        next_value = self._moment_sequence.get(match_id, 0) + 1
        self._moment_sequence[match_id] = next_value
        return next_value

    def _momentum_swing_trigger(self, match_state: MatchState) -> bool:
        """Detect momentum swings while enforcing the 10-minute cooldown."""
        match_id = match_state.match_id or self.match_id
        current_delta = float(match_state.momentum_home - match_state.momentum_away)
        previous_delta = self._last_delta.get(match_id)
        if previous_delta is not None and abs(current_delta - previous_delta) >= 15.0:
            last_minute = self._last_swing_minute.get(match_id)
            if last_minute is None or match_state.minute - last_minute >= 10:
                self._last_swing_minute[match_id] = match_state.minute
                self._last_delta[match_id] = current_delta
                return True
        self._last_delta[match_id] = current_delta
        return False

    def detect(self, match_state: MatchState, event: Event | dict[str, Any]) -> KeyMoment | None:
        """Return a KeyMoment when the supplied event triggers one or more tags."""
        event_obj = _coerce_event(event)
        tags = list(detect_trigger_tags(match_state, event_obj, config_path=self.config_path))

        if self._momentum_swing_trigger(match_state):
            tags.append("momentum_swing")

        if not tags:
            return None

        if "late_game" in tags and "goal" in tags:
            tags = list(dict.fromkeys(["goal", "late_game"] + [tag for tag in tags if tag not in {"goal", "late_game"}]))

        if "momentum_swing" in tags:
            seen = set()
            deduped: list[str] = []
            for tag in tags:
                tag_name = _normalise_trigger_name(tag)
                if tag_name not in seen:
                    deduped.append(tag_name)
                    seen.add(tag_name)
            tags = deduped

        priority_rank = priority_for_tags(tags, config_path=self.config_path)
        match_id = match_state.match_id or event_obj.match_id or self.match_id
        sequence = self._sequence_for(match_id)
        return KeyMoment(
            moment_id=f"{match_id}-km-{sequence:04d}",
            match_id=match_id,
            trigger_event_id=event_obj.event_id,
            trigger_tags=tags,
            priority_rank=priority_rank,
            minute=event_obj.minute,
            second=event_obj.second,
        )

    def process(self, match_state: MatchState, event: Event | dict[str, Any]) -> KeyMoment | None:
        """Compatibility wrapper for orchestration code that prefers a direct method name."""
        return self.detect(match_state, event)

    def consume(self, match_state: MatchState, event: Event | dict[str, Any]) -> KeyMoment | None:
        """Alias for callers using a streaming-style consume API."""
        return self.detect(match_state, event)


def detect_moment(match_state: MatchState, event: Event | dict[str, Any], *, config_path: str | Path | None = None) -> KeyMoment | None:
    """Convenience function returning a ``KeyMoment`` when a trigger fires."""
    return MomentAgent(config_path=config_path).detect(match_state, event)


__all__ = [
    "MomentAgent",
    "detect_moment",
    "detect_trigger_tags",
    "load_priority_config",
    "priority_for_tags",
]
