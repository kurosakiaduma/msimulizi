"""
shared/xg.py — Expected Goals (xG) computation.

Logistic regression trained during the hackathon window from aggregate shot
statistics derived from StatsBomb Open Data (excluding Premier League).
Coefficients are stored in shared/xg_coefficients.json and loaded once at
import time.

See DATA_PROVENANCE.md for training details.
"""

from __future__ import annotations

import json
import math
from pathlib import Path

_COEFF_PATH = Path(__file__).parent / "xg_coefficients.json"

# Loaded lazily so tests that write a fresh coefficients file work without
# re-importing.
_coefficients: dict | None = None


def _load_coefficients() -> dict:
    global _coefficients
    if _coefficients is None:
        with open(_COEFF_PATH) as f:
            _coefficients = json.load(f)
    return _coefficients


def _sigmoid(z: float) -> float:
    """Standard logistic sigmoid, numerically stable."""
    if z >= 0:
        return 1.0 / (1.0 + math.exp(-z))
    e = math.exp(z)
    return e / (1.0 + e)


def compute_xg(
    distance: float,
    angle: float,
    is_header: bool,
    is_penalty: bool,
) -> float:
    """
    Compute Expected Goals for a shot.

    Parameters
    ----------
    distance : float
        Distance from goal centre in pitch units (0–100 scale, where the
        pitch is 100 × 100).  Typical open-play range is 5–40 units.
    angle : float
        Angle to goal in radians.  0 = straight-on from far away;
        π/2 ≈ 1.57 = directly in front of goal.  Clamped to [0, π].
    is_header : bool
        True when the shot is a header.
    is_penalty : bool
        True when the shot is a penalty.  Penalties bypass the distance and
        angle features and use a fixed intercept adjustment.

    Returns
    -------
    float
        Probability of scoring, in the range (0, 1).
    """
    coeff = _load_coefficients()

    intercept: float = coeff["intercept"]
    b_distance: float = coeff["distance"]
    b_angle: float = coeff["angle"]
    b_penalty: float = coeff["is_penalty"]

    # The aggregate training data cannot separate headers from foot shots, so
    # the trained is_header coefficient is always ~0.  We apply a fixed
    # log-odds penalty derived from the football analytics literature
    # (headers convert at roughly 60% of open-play shots → −0.5 log-odds).
    HEADER_LOG_ODDS_PENALTY = -0.5
    b_header: float = coeff.get("is_header") or 0.0
    if b_header == 0.0:
        b_header = HEADER_LOG_ODDS_PENALTY

    if is_penalty:
        z = intercept + b_penalty
    else:
        angle_clamped = max(0.0, min(math.pi, angle))
        z = (
            intercept
            + b_distance * distance
            + b_angle * angle_clamped
            + b_header * int(is_header)
        )

    return _sigmoid(z)


def reload_coefficients() -> None:
    """Force a reload of coefficients from disk (useful in tests)."""
    global _coefficients
    _coefficients = None
