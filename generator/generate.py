"""Synthetic football match generation for the Msimulizi demo pipeline.

This module creates deterministic, fictional match streams from seeded storylines.
It is intentionally lightweight and self-contained so the generator can run
without external data or a live service.
"""

from __future__ import annotations

import random
import re
from pathlib import Path
from typing import Any, Iterator

import yaml

from shared.models import Event, EventType
from shared.xg import compute_xg

_STORYLINES_DIR = Path(__file__).resolve().parent / "storylines"


def make_match_id(storyline: str, seed: int) -> str:
    """Return a stable, human-readable match ID for a storyline and seed.

    The match ID is intended to be deterministic across runs, which makes replay
    and validation logic easier to reason about in tests and demos.
    """
    slug = re.sub(r"[^a-z0-9]+", "-", str(storyline).lower()).strip("-")
    if not slug:
        slug = "synthetic-match"
    return f"{slug}-{seed}"


def _normalise_storyline(storyline: str) -> str:
    """Normalize a storyline name into a stable filesystem-safe slug."""
    return re.sub(r"[^a-z0-9]+", "-", str(storyline).lower()).strip("-")


def _default_storyline_config(storyline: str) -> dict[str, Any]:
    """Provide fallback synthetic storyline data when a YAML config is absent."""
    slug = _normalise_storyline(storyline)
    template = {
        "comeback-from-two-down": {
            "home_team": "Kisumu City",
            "away_team": "Mombasa United",
            "home_players": [
                "Amani Otieno",
                "Khalid Njoroge",
                "Juma Kamau",
                "Davis Wekesa",
                "Eliud Mwangangi",
            ],
            "away_players": [
                "Nuru Mchana",
                "Salim Kivuva",
                "Juma Mwakazi",
                "Asha Njeri",
                "Mbaraka Chacha",
            ],
            "goals": [
                {"team": "away", "minute": 12, "scorer": "Juma Mwakazi"},
                {"team": "away", "minute": 31, "scorer": "Asha Njeri"},
                {"team": "home", "minute": 58, "scorer": "Amani Otieno"},
                {"team": "home", "minute": 77, "scorer": "Khalid Njoroge"},
                {"team": "home", "minute": 88, "scorer": "Juma Kamau"},
            ],
        },
        "red-card-shift": {
            "home_team": "Nairobi North",
            "away_team": "Kisii Falcons",
            "home_players": [
                "Brian Ouma",
                "Eric Muita",
                "Samson Kariuki",
                "Teddy Mwangi",
                "Peter Kioko",
            ],
            "away_players": [
                "Harun Kiptanui",
                "David Karanja",
                "Joseph Miti",
                "Franklin Ndegwa",
                "Lukman Ochieng",
            ],
            "goals": [
                {"team": "home", "minute": 18, "scorer": "Brian Ouma"},
                {"team": "away", "minute": 33, "scorer": "Harun Kiptanui"},
                {"team": "home", "minute": 52, "scorer": "Samson Kariuki"},
                {"team": "home", "minute": 81, "scorer": "Eric Muita"},
            ],
        },
        "late-equaliser": {
            "home_team": "Arusha Rangers",
            "away_team": "Dodoma City",
            "home_players": [
                "Isaac Adera",
                "Moses Ndege",
                "Kevin Mburu",
                "Daniel Mwakio",
                "Tariq Zuberi",
            ],
            "away_players": [
                "Levi Makori",
                "Abdullah Sami",
                "Zuberi Ali",
                "Pius Mnyamala",
                "Noel Kamau",
            ],
            "goals": [
                {"team": "away", "minute": 21, "scorer": "Levi Makori"},
                {"team": "home", "minute": 48, "scorer": "Kevin Mburu"},
                {"team": "away", "minute": 72, "scorer": "Zuberi Ali"},
                {"team": "home", "minute": 86, "scorer": "Moses Ndege"},
            ],
        },
        "dominant-side-loses": {
            "home_team": "Lakeview FC",
            "away_team": "Highlands United",
            "home_players": [
                "Willy Kibet",
                "Ibrahim Juma",
                "Moses Omondi",
                "Abdi Yusuf",
                "Paul Kasa",
            ],
            "away_players": [
                "Yusuf Msuya",
                "Alfred Mpepo",
                "Benson Tiba",
                "Daniel Sanga",
                "Emmanuel Kaso",
            ],
            "goals": [
                {"team": "home", "minute": 11, "scorer": "Willy Kibet"},
                {"team": "home", "minute": 41, "scorer": "Ibrahim Juma"},
                {"team": "away", "minute": 60, "scorer": "Yusuf Msuya"},
                {"team": "away", "minute": 75, "scorer": "Daniel Sanga"},
                {"team": "away", "minute": 90, "scorer": "Emmanuel Kaso"},
            ],
        },
    }
    return template.get(slug, {
        "home_team": "Nairobi City",
        "away_team": "Kisumu Athletic",
        "home_players": ["Amani Oloo", "Juma Kivuva", "Eliud Mwita", "Victor Kivumbi", "Sam Mbeti"],
        "away_players": ["Noah Makena", "Daniel Manda", "Chris Kibet", "Benson Moga", "Owen Mzinga"],
        "goals": [{"team": "home", "minute": 42, "scorer": "Amani Oloo"}],
    })


def _load_storyline_config(storyline: str) -> dict[str, Any]:
    """Load a storyline config from YAML or fall back to a built-in default."""
    slug = _normalise_storyline(storyline)
    file_path = _STORYLINES_DIR / f"{slug}.yaml"
    if file_path.exists():
        with file_path.open("r", encoding="utf-8") as handle:
            data = yaml.safe_load(handle) or {}
        if isinstance(data, dict):
            return data
    return _default_storyline_config(storyline)


def _emit_event(
    *,
    match_id: str,
    sequence: int,
    minute: int,
    second: int,
    event_type: EventType,
    team: str,
    player: str,
    score_home: int,
    score_away: int,
    x_start: float = 50.0,
    y_start: float = 50.0,
    x_end: float | None = None,
    y_end: float | None = None,
    outcome: str | None = None,
    xg: float | None = None,
    is_header: bool = False,
    is_penalty: bool = False,
    pressure: bool = False,
) -> Event:
    """Create a single canonical Event instance from generated match data."""
    return Event(
        event_id=f"{match_id}-{sequence:06d}",
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


def generate_match(storyline: str, seed: int) -> Iterator[Event]:
    """Yield a deterministic synthetic match stream for the requested storyline.

    The stream is built from a seeded RNG plus a small set of fictional club and
    player names, and it emits match metadata plus lifecycle and play events in a
    stable order suitable for replay and pipeline tests.
    """
    rng = random.Random(seed)
    storyline_key = _normalise_storyline(storyline)
    match_id = make_match_id(storyline_key, seed)
    config = _load_storyline_config(storyline)

    home_team = str(config.get("home_team", "Kisumu City"))
    away_team = str(config.get("away_team", "Mombasa United"))
    home_players = list(config.get("home_players", [])) or [
        "Amani Otieno",
        "Khalid Njoroge",
        "Juma Kamau",
        "Davis Wekesa",
        "Eliud Mwangangi",
    ]
    away_players = list(config.get("away_players", [])) or [
        "Nuru Mchana",
        "Salim Kivuva",
        "Juma Mwakazi",
        "Asha Njeri",
        "Mbaraka Chacha",
    ]

    goal_plan = list(config.get("goals", []))
    score_home = 0
    score_away = 0
    sequence = 0

    def emit(event_type: EventType, team: str, player: str, minute: int, second: int, **kwargs: Any) -> Event:
        nonlocal sequence, score_home, score_away
        sequence += 1
        return _emit_event(
            match_id=match_id,
            sequence=sequence,
            minute=minute,
            second=second,
            event_type=event_type,
            team=team,
            player=player,
            score_home=score_home,
            score_away=score_away,
            **kwargs,
        )

    events: list[Event] = []
    events.append(emit(EventType.metadata, home_team, "match", 0, 0, x_start=50.0, y_start=50.0, outcome="start"))
    events.append(emit(EventType.period_start, home_team, "referee", 0, 0, x_start=50.0, y_start=50.0))

    for goal in goal_plan:
        team_side = str(goal.get("team", "home"))
        team_name = home_team if team_side == "home" else away_team
        scorer = str(goal.get("scorer", home_players[0]))
        minute = int(goal.get("minute", 30))
        second = int(goal.get("second", 0))
        # The home side attacks the right-hand goal and the away side attacks
        # the left-hand goal in the pitch visualisation. Keep finishing events
        # inside the attacking penalty area so the replay reflects the
        # underlying football action instead of placing every shot at midfield.
        attacking_x = 88.0 if team_side == "home" else 12.0
        attacking_y = rng.uniform(32.0, 68.0)
        distance = float(goal.get("distance", rng.uniform(7.0, 18.0)))
        angle = float(goal.get("angle", rng.uniform(0.25, 1.2)))
        is_header = bool(goal.get("is_header", rng.random() < 0.25))
        is_penalty = bool(goal.get("is_penalty", False))
        xg_value = compute_xg(distance=distance, angle=angle, is_header=is_header, is_penalty=is_penalty)

        events.append(
            emit(
                EventType.goal,
                team_name,
                scorer,
                minute,
                second,
                x_start=attacking_x,
                y_start=attacking_y,
                x_end=100.0 if team_side == "home" else 0.0,
                y_end=50.0,
                outcome="goal",
                xg=xg_value,
                is_header=is_header,
                is_penalty=is_penalty,
                pressure=rng.random() > 0.4,
            )
        )

        for offset in range(1, 3):
            pass_player = home_players[0] if team_name == away_team else away_players[0]
            pass_team = home_team if team_name == away_team else away_team
            events.append(
                emit(
                    EventType.pass_,
                    pass_team,
                    pass_player,
                    max(1, minute - offset),
                    15 * offset,
                    x_start=40.0 + rng.uniform(-10, 10),
                    y_start=45.0 + rng.uniform(-10, 10),
                    x_end=60.0 + rng.uniform(-8, 8),
                    y_end=50.0 + rng.uniform(-8, 8),
                    outcome="success",
                    pressure=rng.random() > 0.5,
                )
            )

        shot_team = home_team if team_name == home_team else away_team
        shot_player = scorer
        shot_distance = float(goal.get("shot_distance", rng.uniform(10.0, 24.0)))
        shot_angle = float(goal.get("shot_angle", rng.uniform(0.60, 1.50)))
        shot_xg = compute_xg(distance=shot_distance, angle=shot_angle, is_header=is_header, is_penalty=is_penalty)
        shot_x = attacking_x + (
            rng.uniform(-8.0, 4.0) if team_side == "home" else rng.uniform(-4.0, 8.0)
        )
        events.append(
            emit(
                EventType.shot,
                shot_team,
                shot_player,
                minute,
                second + 1,
                x_start=shot_x,
                y_start=attacking_y + rng.uniform(-10.0, 10.0),
                x_end=100.0 if team_side == "home" else 0.0,
                y_end=50.0,
                outcome="goal",
                xg=shot_xg,
                is_header=is_header,
                is_penalty=is_penalty,
                pressure=rng.random() > 0.3,
            )
        )

    events.append(emit(EventType.period_start, away_team, "referee", 45, 0, x_start=50.0, y_start=50.0))
    events.append(emit(EventType.half_time, "match", "referee", 45, 0, x_start=50.0, y_start=50.0, outcome="half_time"))

    for minute in range(1, 91):
        if minute % 16 == 0:
            home_player = home_players[rng.randrange(len(home_players))]
            away_player = away_players[rng.randrange(len(away_players))]
            events.append(
                emit(
                    EventType.pass_,
                    home_team,
                    home_player,
                    minute,
                    rng.randrange(0, 60),
                    x_start=35.0 + rng.uniform(-5, 5),
                    y_start=50.0 + rng.uniform(-10, 10),
                    x_end=60.0 + rng.uniform(-5, 5),
                    y_end=52.0 + rng.uniform(-10, 10),
                    outcome="success",
                    pressure=rng.random() > 0.35,
                )
            )
            events.append(
                emit(
                    EventType.pass_,
                    away_team,
                    away_player,
                    minute,
                    rng.randrange(0, 60),
                    x_start=65.0 + rng.uniform(-5, 5),
                    y_start=50.0 + rng.uniform(-10, 10),
                    x_end=40.0 + rng.uniform(-5, 5),
                    y_end=48.0 + rng.uniform(-10, 10),
                    outcome="success",
                    pressure=rng.random() > 0.35,
                )
            )

    events.append(emit(EventType.full_time, "match", "referee", 90, 0, x_start=50.0, y_start=50.0, outcome="full_time"))

    # Keep the event ordering stable and deterministic.
    events.sort(key=lambda event: (event.period, event.minute, event.second, event.event_id))
    
    current_score_home = 0
    current_score_away = 0
    for event in events:
        if event.event_type == EventType.goal:
            if event.team == home_team:
                current_score_home += 1
            else:
                current_score_away += 1
        event.score_home = current_score_home
        event.score_away = current_score_away
        
    return iter(events)


__all__ = ["make_match_id", "generate_match"]
