"""Raw approach angles from Statcast's constant-acceleration trajectory fit."""

from __future__ import annotations

from math import atan2, degrees, isfinite, sqrt

TRAJECTORY_FIELDS = ("vx0", "vy0", "vz0", "ax", "ay", "az")
ANGLE_FIELDS = (*TRAJECTORY_FIELDS, "vaa", "haa", "approach_angle_version")
ANGLE_VERSION = 1
REFERENCE_Y_FT = 50.0
PLATE_Y_FT = 17.0 / 12.0


def _finite(value):
    try:
        return value is not None and isfinite(float(value))
    except (TypeError, ValueError):
        return False


def approach_angles(*, vx0=None, vy0=None, vz0=None, ax=None, ay=None, az=None):
    """Return (VAA, HAA) in degrees at the front plane of home plate.

    Implements Chamberlain's published yz/x-y plane approach-angle formulas.
    Statcast velocities are referenced to y=50 ft, NOT the release point.
    Positive z is up; positive x is the catcher's right. No handedness flip.
    Missing or impossible fits yield None for the affected angle.
    """
    if not (_finite(vy0) and _finite(ay)):
        return None, None
    vy0, ay = float(vy0), float(ay)
    distance = REFERENCE_Y_FT - PLATE_Y_FT
    discriminant = vy0 * vy0 - 2 * ay * distance
    if vy0 >= 0 or not isfinite(discriminant) or discriminant <= 0:
        return None, None
    forward_speed = sqrt(discriminant)  # -vy_f; the ball is traveling toward the plate.
    # Algebraically (vy_f - vy0)/ay, rationalized to avoid cancellation and
    # to handle ay=0 without dividing by zero.
    flight_time = 2 * distance / (-vy0 + forward_speed)
    if not isfinite(flight_time) or flight_time <= 0:
        return None, None

    def angle(velocity, acceleration):
        if not (_finite(velocity) and _finite(acceleration)):
            return None
        final = float(velocity) + float(acceleration) * flight_time
        return degrees(atan2(final, forward_speed)) if isfinite(final) else None

    return angle(vz0, az), angle(vx0, ax)


def trajectory_record(row, *, checked=False):
    """Keep full source precision; calculated values are rounded only for display."""
    record = {key: float(row[key]) if _finite(row.get(key)) else None for key in TRAJECTORY_FIELDS}
    record["vaa"], record["haa"] = approach_angles(**record)
    record["approach_angle_version"] = (
        ANGLE_VERSION
        if checked or any(record[key] is not None for key in TRAJECTORY_FIELDS)
        else None
    )
    return record
