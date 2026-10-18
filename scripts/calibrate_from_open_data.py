"""
scripts/calibrate_from_open_data.py

Downloads the StatsBomb Open Data repository (zip), extracts shot and pass
events, computes aggregate calibration statistics (excluding all Premier
League competition files), writes them to generator/calibration_aggregates.json,
then deletes every raw file so that no raw event data remains in the repo.

Usage:
    python -m scripts.calibrate_from_open_data

Environment variables (optional):
    STATSBOMB_OPEN_DATA_URL   Override the zip download URL
    CALIBRATION_SCRATCH_DIR   Override the temporary scratch directory
                              (defaults to .calibration_scratch/, gitignored)

The aggregates written are:
    pass_completion_by_zone         dict[zone_key, {attempts, completions, rate}]
    shot_conversion_by_distance     dict[distance_bucket, {attempts, goals, rate}]
    shot_conversion_by_angle        dict[angle_bucket,    {attempts, goals, rate}]
    events_per_minute               float
    pressure_rate                   float  (pressure events / total events)
    shot_count                      int
    pass_count                      int
    total_events                    int
    total_minutes                   float
    sources_consulted               list[str]
"""

from __future__ import annotations

import io
import json
import math
import os
import shutil
import sys
import urllib.request
import zipfile
from collections import defaultdict
from pathlib import Path

# ---------------------------------------------------------------------------
# Configuration
# ---------------------------------------------------------------------------

STATSBOMB_OPEN_DATA_URL = os.environ.get(
    "STATSBOMB_OPEN_DATA_URL",
    "https://github.com/statsbomb/open-data/archive/refs/heads/master.zip",
)

SCRATCH_DIR = Path(
    os.environ.get("CALIBRATION_SCRATCH_DIR", ".calibration_scratch")
)

OUTPUT_PATH = Path("generator/calibration_aggregates.json")

# Competitions to exclude (competition_id values from StatsBomb open data).
# Premier League = competition_id 2.
EXCLUDED_COMPETITION_IDS: set[int] = {2}

# Pitch dimensions (StatsBomb native: 120 × 80 yards)
PITCH_LENGTH = 120.0
PITCH_WIDTH = 80.0
GOAL_X = 120.0
GOAL_Y = 40.0  # centre of goal

# Distance buckets (yards from goal)
DISTANCE_BUCKETS = [0, 6, 12, 18, 25, 35, 50, 200]

# Angle buckets (radians from straight ahead, 0 = central)
ANGLE_BUCKETS = [0.0, 0.2, 0.4, 0.6, 0.8, 1.0, 1.2, math.pi]

# Pitch thirds for pass-completion zones
#   defending_third:  x in [0,  40)
#   middle_third:     x in [40, 80)
#   attacking_third:  x in [80, 120]
ZONE_BOUNDARIES = [0, 40, 80, 120]
ZONE_NAMES = ["defending_third", "middle_third", "attacking_third"]


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _distance_bucket(dist: float) -> str:
    for i in range(len(DISTANCE_BUCKETS) - 1):
        if dist < DISTANCE_BUCKETS[i + 1]:
            return f"{DISTANCE_BUCKETS[i]}-{DISTANCE_BUCKETS[i+1]}y"
    return f"{DISTANCE_BUCKETS[-2]}+y"


def _angle_bucket(ang: float) -> str:
    for i in range(len(ANGLE_BUCKETS) - 1):
        if ang < ANGLE_BUCKETS[i + 1]:
            lo = f"{ANGLE_BUCKETS[i]:.1f}"
            hi = f"{ANGLE_BUCKETS[i+1]:.1f}"
            return f"{lo}-{hi}rad"
    return f"{ANGLE_BUCKETS[-2]:.1f}+rad"


def _pitch_zone(x: float) -> str:
    for i in range(len(ZONE_BOUNDARIES) - 1):
        if x < ZONE_BOUNDARIES[i + 1]:
            return ZONE_NAMES[i]
    return ZONE_NAMES[-1]


def _shot_distance(x: float, y: float) -> float:
    return math.sqrt((GOAL_X - x) ** 2 + (GOAL_Y - y) ** 2)


def _shot_angle(x: float, y: float) -> float:
    """
    Angle subtended by the goal mouth at the shot location (radians).
    Uses the two goalposts at (120, 36) and (120, 44) — 8-yard goal.
    """
    post1 = (GOAL_X, 36.0)
    post2 = (GOAL_X, 44.0)
    # Vectors from shot location to each post
    v1 = (post1[0] - x, post1[1] - y)
    v2 = (post2[0] - x, post2[1] - y)
    dot = v1[0] * v2[0] + v1[1] * v2[1]
    mag1 = math.sqrt(v1[0] ** 2 + v1[1] ** 2)
    mag2 = math.sqrt(v2[0] ** 2 + v2[1] ** 2)
    if mag1 == 0 or mag2 == 0:
        return 0.0
    cos_angle = max(-1.0, min(1.0, dot / (mag1 * mag2)))
    return math.acos(cos_angle)


# ---------------------------------------------------------------------------
# Download and extract
# ---------------------------------------------------------------------------

def download_open_data(scratch: Path) -> Path:
    scratch.mkdir(parents=True, exist_ok=True)
    zip_path = scratch / "open-data-master.zip"
    print(f"Downloading StatsBomb Open Data from {STATSBOMB_OPEN_DATA_URL} …")

    req = urllib.request.urlopen(STATSBOMB_OPEN_DATA_URL)  # noqa: S310
    total = int(req.headers.get("Content-Length", 0))
    chunk_size = 1024 * 1024  # 1 MB chunks
    downloaded = 0

    with open(zip_path, "wb") as out:
        while True:
            chunk = req.read(chunk_size)
            if not chunk:
                break
            out.write(chunk)
            downloaded += len(chunk)
            if total:
                pct = downloaded / total * 100
                bar_filled = int(pct / 2)
                bar = "#" * bar_filled + "-" * (50 - bar_filled)
                print(
                    f"\r  [{bar}] {pct:5.1f}%  "
                    f"{downloaded / 1_048_576:6.1f} / {total / 1_048_576:.1f} MB",
                    end="",
                    flush=True,
                )
            else:
                print(
                    f"\r  {downloaded / 1_048_576:6.1f} MB downloaded …",
                    end="",
                    flush=True,
                )

    print()  # newline after progress bar
    print(f"  Saved to {zip_path} ({zip_path.stat().st_size / 1_048_576:.1f} MB)")

    extract_dir = scratch / "open-data-master"
    n_files = 0
    print("  Extracting …", end="", flush=True)
    with zipfile.ZipFile(zip_path) as zf:
        members = zf.namelist()
        total_members = len(members)
        for i, member in enumerate(members, 1):
            zf.extract(member, scratch)
            n_files += 1
            if i % 500 == 0 or i == total_members:
                print(
                    f"\r  Extracting … {i}/{total_members} files",
                    end="",
                    flush=True,
                )
    print(f"\r  Extracted {n_files} files to {extract_dir}        ")
    return extract_dir


# ---------------------------------------------------------------------------
# Filter competitions
# ---------------------------------------------------------------------------

def load_allowed_match_ids(extract_dir: Path) -> set[str]:
    """
    Parse competitions.json to find match_ids from non-excluded competitions.
    Returns the set of allowed match_id strings.
    """
    competitions_path = extract_dir / "data" / "competitions.json"
    if not competitions_path.exists():
        raise FileNotFoundError(f"competitions.json not found at {competitions_path}")

    with open(competitions_path) as f:
        competitions = json.load(f)

    allowed_season_pairs: set[tuple[int, int]] = set()
    excluded_names: list[str] = []
    for comp in competitions:
        cid = comp["competition_id"]
        sid = comp["season_id"]
        cname = comp.get("competition_name", "")
        if cid in EXCLUDED_COMPETITION_IDS:
            excluded_names.append(f"{cname} (id={cid}, season={sid})")
            continue
        allowed_season_pairs.add((cid, sid))

    print(f"  Excluded competitions: {excluded_names}")
    print(f"  Allowed (competition_id, season_id) pairs: {len(allowed_season_pairs)}")

    # Walk matches directory
    matches_dir = extract_dir / "data" / "matches"
    allowed_match_ids: set[str] = set()
    if not matches_dir.exists():
        return allowed_match_ids

    for comp_dir in matches_dir.iterdir():
        if not comp_dir.is_dir():
            continue
        try:
            cid = int(comp_dir.name)
        except ValueError:
            continue
        for season_file in comp_dir.iterdir():
            try:
                sid = int(season_file.stem)
            except ValueError:
                continue
            if (cid, sid) not in allowed_season_pairs:
                continue
            with open(season_file) as f:
                matches = json.load(f)
            for m in matches:
                allowed_match_ids.add(str(m["match_id"]))

    print(f"  Allowed match count: {len(allowed_match_ids)}")
    return allowed_match_ids


# ---------------------------------------------------------------------------
# Aggregate computation
# ---------------------------------------------------------------------------

def compute_aggregates(extract_dir: Path, allowed_match_ids: set[str]) -> dict:
    events_dir = extract_dir / "data" / "events"
    if not events_dir.exists():
        raise FileNotFoundError(f"events directory not found at {events_dir}")

    # Accumulators
    pass_zone: dict[str, dict[str, int]] = defaultdict(lambda: {"attempts": 0, "completions": 0})
    shot_dist: dict[str, dict[str, int]] = defaultdict(lambda: {"attempts": 0, "goals": 0})
    shot_ang:  dict[str, dict[str, int]] = defaultdict(lambda: {"attempts": 0, "goals": 0})
    total_events = 0
    total_pressure = 0
    total_minutes = 0.0
    shot_count = 0
    pass_count = 0

    event_files = sorted(events_dir.glob("*.json"))
    processed = 0

    for event_file in event_files:
        match_id = event_file.stem
        if match_id not in allowed_match_ids:
            continue

        with open(event_file) as f:
            events = json.load(f)

        match_max_minute = 0.0

        for ev in events:
            etype = ev.get("type", {}).get("id")
            total_events += 1

            minute = ev.get("minute", 0) or 0
            second = ev.get("second", 0) or 0
            match_time = minute + second / 60.0
            if match_time > match_max_minute:
                match_max_minute = match_time

            # Pressure events (type id 17 in StatsBomb)
            if etype == 17:
                total_pressure += 1

            # Pass events (type id 30)
            if etype == 30:
                pass_count += 1
                loc = ev.get("location")
                pass_data = ev.get("pass", {})
                if loc and len(loc) >= 2:
                    zone = _pitch_zone(loc[0])
                    pass_zone[zone]["attempts"] += 1
                    outcome = pass_data.get("outcome", {})
                    # Successful pass: outcome is absent or outcome.id != 9 (incomplete)
                    if outcome is None or outcome.get("id") not in (9, 74, 75, 76, 77):
                        pass_zone[zone]["completions"] += 1

            # Shot events (type id 16)
            if etype == 16:
                shot_count += 1
                loc = ev.get("location")
                shot_data = ev.get("shot", {})
                outcome_id = shot_data.get("outcome", {}).get("id")
                is_goal = outcome_id == 97  # StatsBomb outcome id for Goal

                if loc and len(loc) >= 2:
                    sx, sy = loc[0], loc[1]
                    dist = _shot_distance(sx, sy)
                    ang = _shot_angle(sx, sy)

                    db = _distance_bucket(dist)
                    ab = _angle_bucket(ang)

                    shot_dist[db]["attempts"] += 1
                    shot_ang[ab]["attempts"] += 1
                    if is_goal:
                        shot_dist[db]["goals"] += 1
                        shot_ang[ab]["goals"] += 1

        total_minutes += match_max_minute
        processed += 1
        if processed % 50 == 0:
            print(f"  Processed {processed}/{len(event_files)} event files …")

    print(f"  Processed {processed} allowed matches, {total_events:,} events")

    # Build rates
    def _rate(num: int, denom: int) -> float:
        return round(num / denom, 6) if denom > 0 else 0.0

    pass_completion_by_zone = {
        zone: {
            "attempts": v["attempts"],
            "completions": v["completions"],
            "rate": _rate(v["completions"], v["attempts"]),
        }
        for zone, v in sorted(pass_zone.items())
    }

    shot_conversion_by_distance = {
        bucket: {
            "attempts": v["attempts"],
            "goals": v["goals"],
            "rate": _rate(v["goals"], v["attempts"]),
        }
        for bucket, v in sorted(shot_dist.items())
    }

    shot_conversion_by_angle = {
        bucket: {
            "attempts": v["attempts"],
            "goals": v["goals"],
            "rate": _rate(v["goals"], v["attempts"]),
        }
        for bucket, v in sorted(shot_ang.items())
    }

    events_per_minute = round(total_events / total_minutes, 4) if total_minutes > 0 else 0.0
    pressure_rate = round(total_pressure / total_events, 6) if total_events > 0 else 0.0

    return {
        "pass_completion_by_zone": pass_completion_by_zone,
        "shot_conversion_by_distance": shot_conversion_by_distance,
        "shot_conversion_by_angle": shot_conversion_by_angle,
        "events_per_minute": events_per_minute,
        "pressure_rate": pressure_rate,
        "shot_count": shot_count,
        "pass_count": pass_count,
        "total_events": total_events,
        "total_minutes": round(total_minutes, 2),
        "sources_consulted": [
            "StatsBomb Open Data (https://github.com/statsbomb/open-data)",
            "Premier League competition (competition_id=2) EXCLUDED",
        ],
    }


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def main() -> None:
    print("=== Calibrate from Open Data ===")

    # Download
    extract_dir = download_open_data(SCRATCH_DIR)

    # Filter
    print("Loading competition/match index …")
    allowed_match_ids = load_allowed_match_ids(extract_dir)

    # Aggregate
    print("Computing aggregates …")
    aggregates = compute_aggregates(extract_dir, allowed_match_ids)

    # Write output
    OUTPUT_PATH.parent.mkdir(parents=True, exist_ok=True)
    with open(OUTPUT_PATH, "w") as f:
        json.dump(aggregates, f, indent=2)
    print(f"Wrote aggregates to {OUTPUT_PATH}")

    # Delete raw files
    print(f"Deleting scratch directory {SCRATCH_DIR} …")
    shutil.rmtree(SCRATCH_DIR)
    print("  Done — no raw data remains.")

    print("\nCalibration complete.")
    print(f"  Matches processed : {aggregates['total_minutes']:.0f} match-minutes")
    print(f"  Total events      : {aggregates['total_events']:,}")
    print(f"  Shots             : {aggregates['shot_count']:,}")
    print(f"  Passes            : {aggregates['pass_count']:,}")


if __name__ == "__main__":
    main()
