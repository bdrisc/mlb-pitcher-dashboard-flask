"""Velocity and movement gaps between filtered pitch-type centroids."""

from __future__ import annotations

from itertools import combinations
from math import hypot, inf
from typing import Any

from sqlalchemy import func, select

from app.extensions import db
from app.models import Game, Pitch
from app.services.pitch_data import PITCH_NAME_MAP

FASTBALL_TYPES = {"FF", "SI", "FA", "FC"}


def _finite(column):
    # Both supported databases compare infinities; this also excludes Postgres NaN.
    return (column > -inf) & (column < inf)


def separation_pairs(pitch_types: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """One unordered pair per type; signed differences are B minus A."""
    pairs = []
    for a, b in combinations(pitch_types, 2):
        velocity_difference = (
            None
            if a["velocity_mph"] is None or b["velocity_mph"] is None
            else b["velocity_mph"] - a["velocity_mph"]
        )
        movement_known = all(
            pitch[key] is not None
            for pitch in (a, b)
            for key in ("horizontal_break_inches", "induced_vertical_break_inches")
        )
        hb = b["horizontal_break_inches"] - a["horizontal_break_inches"] if movement_known else None
        ivb = (
            b["induced_vertical_break_inches"] - a["induced_vertical_break_inches"]
            if movement_known
            else None
        )
        pairs.append(
            {
                "pitch_a": a["pitch_type"],
                "pitch_b": b["pitch_type"],
                "velocity_gap_mph": None
                if velocity_difference is None
                else abs(velocity_difference),
                "velocity_difference_mph": velocity_difference,
                "horizontal_difference_inches": hb,
                "vertical_difference_inches": ivb,
                "movement_gap_inches": None if hb is None else hypot(hb, ivb),
            }
        )
    return pairs


def build_pitch_separation(conditions: list[Any]) -> dict[str, Any]:
    velocity_known = _finite(Pitch.velocity)
    movement_known = _finite(Pitch.horizontal_break_inches) & _finite(Pitch.vertical_break_inches)
    rows = db.session.execute(
        select(
            Pitch.pitch_type,
            func.count(Pitch.pitch_id).label("pitch_count"),
            func.count(Pitch.pitch_id).filter(velocity_known).label("velocity_pitch_count"),
            func.count(Pitch.pitch_id).filter(movement_known).label("movement_pitch_count"),
            func.avg(Pitch.velocity).filter(velocity_known).label("velocity_mph"),
            func.avg(Pitch.horizontal_break_inches)
            .filter(movement_known)
            .label("horizontal_break_inches"),
            func.avg(Pitch.vertical_break_inches)
            .filter(movement_known)
            .label("induced_vertical_break_inches"),
        )
        .join(Game, Game.game_pk == Pitch.game_pk)
        .where(
            *conditions,
            Pitch.pitch_type.notin_(("", "UN")),
            func.coalesce(func.lower(Pitch.description), "").notin_(
                ("automatic_ball", "automatic_strike")
            ),
        )
        .group_by(Pitch.pitch_type)
        .order_by(func.count(Pitch.pitch_id).desc(), Pitch.pitch_type)
    ).mappings()
    # Keep full precision for calculating gaps. Rounding belongs in the display.
    types = [
        {**dict(row), "pitch_name": PITCH_NAME_MAP.get(row["pitch_type"], row["pitch_type"])}
        for row in rows
    ]
    reference = next(
        (
            row["pitch_type"]
            for row in types
            if row["pitch_type"] in FASTBALL_TYPES
            and (row["velocity_pitch_count"] or row["movement_pitch_count"])
        ),
        None,
    )
    return {
        "reference_pitch_type": reference,
        "difference_convention": "pitch_b_minus_pitch_a",
        "pitch_types": types,
        "pairs": separation_pairs(types),
    }
