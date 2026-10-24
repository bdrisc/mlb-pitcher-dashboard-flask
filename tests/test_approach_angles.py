"""Check plate-plane geometry, independent numerical slopes and source handling."""

import csv
import math
from pathlib import Path

import pytest

from app.services.approach_angles import approach_angles


def numerical_angles(vx0, vy0, vz0, ax, ay, az):
    """Independent bisection of position, then central differences at the plate."""

    def position(t):
        return (
            vx0 * t + ax * t * t / 2,
            50 + vy0 * t + ay * t * t / 2,
            vz0 * t + az * t * t / 2,
        )

    lower, upper = 0.0, 1.0
    for _ in range(70):
        midpoint = (lower + upper) / 2
        if position(midpoint)[1] > 17 / 12:
            lower = midpoint
        else:
            upper = midpoint
    t = (lower + upper) / 2
    before, after = position(t - 1e-5), position(t + 1e-5)
    dx, dy, dz = (b - a for a, b in zip(before, after, strict=True))
    return math.degrees(math.atan2(dz, -dy)), math.degrees(math.atan2(dx, -dy))


def test_real_statcast_fits_match_independent_position_derivatives():
    path = Path(__file__).parent / "fixtures" / "statcast_approach_angles.csv"
    with path.open() as source:
        rows = list(csv.DictReader(source))
    assert len(rows) >= 20
    assert {r["p_throws"] for r in rows} == {"L", "R"}
    for row in rows:
        values = {key: float(row[key]) for key in ("vx0", "vy0", "vz0", "ax", "ay", "az")}
        expected = numerical_angles(**values)
        assert approach_angles(**values) == pytest.approx(expected, abs=1e-8)
        # Independent transcription of Chamberlain's published equations.
        vy_f = -math.sqrt(values["vy0"] ** 2 - 2 * values["ay"] * (50 - 17 / 12))
        t = (vy_f - values["vy0"]) / values["ay"]
        published = tuple(
            -math.degrees(math.atan((values[v] + values[a] * t) / vy_f))
            for v, a in (("vz0", "az"), ("vx0", "ax"))
        )
        assert approach_angles(**values) == pytest.approx(published, abs=1e-10)


def test_zero_drag_known_angles_and_mirrored_horizontal_sign():
    values = dict(vx0=10, vy0=-100, vz0=-10, ax=0, ay=0, az=0)
    vaa, haa = approach_angles(**values)
    assert vaa == pytest.approx(-5.7105931375)
    assert haa == pytest.approx(5.7105931375)
    assert approach_angles(**{**values, "vx0": -10}) == pytest.approx((vaa, -haa))
    assert approach_angles(**{**values, "ay": 1e-12}) == pytest.approx((vaa, haa))


@pytest.mark.parametrize(
    "changes", [{"vy0": 100}, {"ay": 200}, {"vy0": None}, {"ay": float("inf")}]
)
def test_impossible_or_missing_forward_motion_is_unavailable(changes):
    values = dict(vx0=1, vy0=-100, vz0=-10, ax=0, ay=20, az=-20)
    assert approach_angles(**{**values, **changes}) == (None, None)


def test_missing_one_axis_does_not_zero_or_discard_other_axis():
    values = dict(vx0=1, vy0=-100, vz0=-10, ax=0, ay=20, az=-20)
    expected = approach_angles(**values)
    assert approach_angles(**{**values, "vx0": None}) == (expected[0], None)
    assert approach_angles(**{**values, "az": float("nan")}) == (None, expected[1])
