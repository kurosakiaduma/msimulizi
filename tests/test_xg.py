"""
Unit tests for shared/xg.py — compute_xg parametrised shot geometries,
penalty and header effects, output in [0, 1].

Requirements: 1.6, 15.1, 16.4
"""

from __future__ import annotations

import math
import pytest

from shared.xg import compute_xg


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _xg(distance: float, angle: float, *, header: bool = False, penalty: bool = False) -> float:
    return compute_xg(distance, angle, header, penalty)


# ---------------------------------------------------------------------------
# Output range
# ---------------------------------------------------------------------------

class TestOutputRange:
    @pytest.mark.parametrize("distance,angle", [
        (6.0, 1.4),
        (12.0, 1.0),
        (18.0, 0.6),
        (30.0, 0.3),
        (40.0, 0.1),
    ])
    def test_output_between_zero_and_one(self, distance, angle):
        result = _xg(distance, angle)
        assert 0.0 < result < 1.0, f"xG={result} out of (0,1) for dist={distance}, angle={angle}"

    def test_penalty_between_zero_and_one(self):
        result = _xg(12.0, 1.0, penalty=True)
        assert 0.0 < result < 1.0

    def test_header_between_zero_and_one(self):
        result = _xg(12.0, 0.8, header=True)
        assert 0.0 < result < 1.0


# ---------------------------------------------------------------------------
# Shot geometry effects
# ---------------------------------------------------------------------------

class TestShotGeometry:
    def test_closer_shot_has_higher_xg(self):
        """A shot from 10 yards should have higher xG than one from 30 yards."""
        close = _xg(10.0, 0.8)
        far   = _xg(30.0, 0.8)
        assert close > far, f"close={close:.4f} not > far={far:.4f}"

    def test_wider_angle_has_higher_xg(self):
        """A shot with a wider goal-mouth angle should have higher xG."""
        wide   = _xg(18.0, 1.2)
        narrow = _xg(18.0, 0.2)
        assert wide > narrow, f"wide={wide:.4f} not > narrow={narrow:.4f}"

    def test_extreme_distance_very_low_xg(self):
        """A shot from 45 yards should be very unlikely to score."""
        result = _xg(45.0, 0.15)
        assert result < 0.10, f"Expected xG < 0.10 from 45 yards, got {result:.4f}"

    def test_close_central_shot_meaningful_xg(self):
        """A shot from 8 yards centrally should have a non-trivial xG."""
        result = _xg(8.0, 1.3)
        assert result > 0.20, f"Expected xG > 0.20 for close central shot, got {result:.4f}"


# ---------------------------------------------------------------------------
# Penalty effect
# ---------------------------------------------------------------------------

class TestPenalty:
    def test_penalty_xg_above_0_6(self):
        """Penalties should convert at well above 60 %."""
        result = _xg(12.0, 1.0, penalty=True)
        assert result > 0.60, f"Penalty xG {result:.4f} unexpectedly low"

    def test_penalty_xg_higher_than_equivalent_open_play(self):
        """A penalty should have higher xG than the same geometry as open play."""
        pen   = _xg(12.0, 1.0, penalty=True)
        open_ = _xg(12.0, 1.0, penalty=False)
        assert pen > open_, f"pen={pen:.4f} not > open={open_:.4f}"

    def test_penalty_ignores_distance(self):
        """Passing different distances to a penalty shot should not change the result."""
        result_a = _xg(12.0, 1.0, penalty=True)
        result_b = _xg(35.0, 0.2, penalty=True)
        assert result_a == pytest.approx(result_b, abs=1e-9), (
            "Penalty xG should be independent of distance and angle"
        )


# ---------------------------------------------------------------------------
# Header effect
# ---------------------------------------------------------------------------

class TestHeader:
    def test_header_lower_xg_than_foot(self):
        """Headers should convert at a lower rate than foot shots from same position."""
        foot   = _xg(15.0, 0.9, header=False)
        header = _xg(15.0, 0.9, header=True)
        assert header < foot, f"header={header:.4f} not < foot={foot:.4f}"

    def test_header_still_positive(self):
        """Headers from close range should still have a positive xG."""
        result = _xg(10.0, 1.0, header=True)
        assert result > 0.0


# ---------------------------------------------------------------------------
# Angle clamping
# ---------------------------------------------------------------------------

class TestAngleClamping:
    def test_negative_angle_clamped(self):
        """Negative angles should be clamped to 0 and return the same as angle=0."""
        result_neg  = _xg(20.0, -0.5)
        result_zero = _xg(20.0, 0.0)
        assert result_neg == pytest.approx(result_zero, abs=1e-9)

    def test_angle_above_pi_clamped(self):
        """Angles above π should be clamped to π."""
        result_over = _xg(20.0, math.pi + 1.0)
        result_pi   = _xg(20.0, math.pi)
        assert result_over == pytest.approx(result_pi, abs=1e-9)
