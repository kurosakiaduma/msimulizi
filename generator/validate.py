"""Validation helpers for the synthetic match generator.

This module exercises generated matches against the storyline calibration bands
and exits non-zero when a storyline drifts outside the allowed range.
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path
from typing import Any

import yaml

from generator.generate import generate_match
from shared.models import EventType

_VALIDATION_PATH = Path(__file__).resolve().parent / "validation_config.yaml"


def _normalise_metric_name(name: str) -> str:
    """Normalise config keys so they match the generated statistics format."""
    return name.strip().lower().replace("-", "_")


def _coerce_bounds(raw: Any) -> tuple[float, float] | None:
    """Convert a config bound definition into a (min, max) numeric tuple."""
    if isinstance(raw, dict):
        if {"min", "max"}.issubset(raw):
            return float(raw["min"]), float(raw["max"])
        return None
    if isinstance(raw, (list, tuple)) and len(raw) == 2:
        return float(raw[0]), float(raw[1])
    return None


def _summarise_match(storyline: str, seed: int = 42) -> dict[str, float | int]:
    """Generate a compact set of summary statistics for one storyline match."""
    events = list(generate_match(storyline, seed))
    stats: dict[str, float | int] = {
        "total_events": len(events),
        "total_shots": 0,
        "goals_home": 0,
        "goals_away": 0,
        "xg_home": 0.0,
        "xg_away": 0.0,
    }

    config = _load_storyline_config(storyline)
    home_team = str(config.get("home_team", ""))
    away_team = str(config.get("away_team", ""))

    for event in events:
        if event.event_type == EventType.shot:
            stats["total_shots"] = int(stats["total_shots"]) + 1
            if event.team == home_team:
                stats["xg_home"] = float(stats["xg_home"]) + float(event.xg or 0.0)
            elif event.team == away_team:
                stats["xg_away"] = float(stats["xg_away"]) + float(event.xg or 0.0)
        elif event.event_type == EventType.goal:
            if event.team == home_team:
                stats["goals_home"] = int(stats["goals_home"]) + 1
            elif event.team == away_team:
                stats["goals_away"] = int(stats["goals_away"]) + 1
    return stats


def _load_storyline_config(storyline: str) -> dict[str, Any]:
    """Load a storyline YAML file when it exists for team metadata lookups."""
    path = Path(__file__).resolve().parent / "storylines" / f"{_normalise_metric_name(storyline)}.yaml"
    if path.exists():
        with path.open("r", encoding="utf-8") as handle:
            loaded = yaml.safe_load(handle) or {}
        if isinstance(loaded, dict):
            return loaded
    return {}


def validate_storyline(storyline: str, seed: int = 42, stats: dict[str, Any] | None = None, config_path: str | Path | None = None) -> bool:
    """Check whether a storyline stays within its configured calibration bounds."""
    if stats is None:
        stats = _summarise_match(storyline, seed)

    path = Path(config_path) if config_path is not None else _VALIDATION_PATH
    config_data: dict[str, Any] = {}
    if path.exists():
        with path.open("r", encoding="utf-8") as handle:
            config_data = yaml.safe_load(handle) or {}
    if not isinstance(config_data, dict):
        return True

    story_key = _normalise_metric_name(storyline)
    bands = config_data.get(story_key, {})
    if not isinstance(bands, dict):
        return True

    for metric_name, bounds in bands.items():
        key = _normalise_metric_name(metric_name)
        if key not in stats:
            continue
        numeric_bounds = _coerce_bounds(bounds)
        if numeric_bounds is None:
            continue
        minimum, maximum = numeric_bounds
        value = float(stats[key])
        if value < minimum or value > maximum:
            return False
    return True


def validate_all(seed: int = 42, config_path: str | Path | None = None) -> bool:
    """Validate every configured storyline against the calibration bands."""
    path = Path(config_path) if config_path is not None else _VALIDATION_PATH
    if not path.exists():
        return True
    with path.open("r", encoding="utf-8") as handle:
        config = yaml.safe_load(handle) or {}
    if not isinstance(config, dict):
        return True
    for storyline in config:
        if not validate_storyline(str(storyline), seed=seed, config_path=path):
            return False
    return True


def _main(argv: list[str] | None = None) -> int:
    """Run the validation script entry point for CLI usage."""
    parser = argparse.ArgumentParser(description="Validate the synthetic storyline calibration bands.")
    parser.add_argument("--storyline", type=str, default=None, help="Check just one storyline.")
    parser.add_argument("--seed", type=int, default=42, help="Seed used for generated match statistics.")
    args = parser.parse_args(argv)

    if args.storyline:
        ok = validate_storyline(args.storyline, seed=args.seed)
        if not ok:
            print(f"Calibration drift detected for storyline '{args.storyline}'.", file=sys.stderr)
            return 1
        return 0

    ok = validate_all(seed=args.seed)
    if not ok:
        print("Calibration drift detected in one or more storylines.", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(_main())
