"""Pitch-location contact damage relative to a matched league cohort.

Aggregate sufficient statistics by pitch type, batter hand and normalized
3x3 strike-zone cell, so the browser can switch metrics/hand/pitch without
running additional database queries or averaging already-rounded rates.
"""

from __future__ import annotations

from dataclasses import replace
from typing import Any

from sqlalchemy import case, func, select
from sqlalchemy.sql.elements import ColumnElement

from app.extensions import db
from app.models import Game, Pitch, Player
from app.services.database_queries import pitch_filter_conditions
from app.services.filters import PitchFilters
from app.services.pitch_data import PITCH_NAME_MAP

# Matches the fixed horizontal strike zone shown in the location KDE charts.
STRIKE_HALF_WIDTH_FT = 0.88
MIN_PITCHER_CONTACTS = 10
MIN_LEAGUE_CONTACTS = 30


def _zone_coordinates() -> tuple[Any, Any]:
    """Return catcher-view x and batter-relative height bins (0..2).

    y=0 is the bottom third; y=2 is the upper third. Compare heights
    relative to each individual hitter's strike-zone boundaries.
    """
    x_third = STRIKE_HALF_WIDTH_FT / 3
    x_bin = case(
        (Pitch.plate_x < -x_third, 0),
        (Pitch.plate_x < x_third, 1),
        else_=2,
    )
    height = Pitch.strike_zone_top - Pitch.strike_zone_bottom
    relative_height_times_three = 3 * (Pitch.plate_z - Pitch.strike_zone_bottom)
    y_bin = case(
        (relative_height_times_three < height, 0),
        (relative_height_times_three < 2 * height, 1),
        else_=2,
    )
    return x_bin, y_bin


def _eligible_contact() -> tuple[ColumnElement[bool], ...]:
    """Use the same classified-contact sample as the profile's EV/xwOBAcon."""
    return (
        Pitch.batter_side.in_(("R", "L")),
        Pitch.batted_ball_type.is_not(None),
        Pitch.batted_ball_type != "",
        (Pitch.exit_velocity.is_not(None) | Pitch.estimated_woba.is_not(None)),
        Pitch.plate_x.between(-STRIKE_HALF_WIDTH_FT, STRIKE_HALF_WIDTH_FT),
        Pitch.strike_zone_bottom.is_not(None),
        Pitch.strike_zone_top.is_not(None),
        Pitch.strike_zone_top > Pitch.strike_zone_bottom,
        Pitch.plate_z >= Pitch.strike_zone_bottom,
        Pitch.plate_z <= Pitch.strike_zone_top,
    )


def _aggregate(
    conditions: list[ColumnElement[bool]], *, throwing_hand: str | None = None
) -> list[dict[str, Any]]:
    x_bin, y_bin = _zone_coordinates()
    statement = (
        select(
            Pitch.pitch_type,
            Pitch.batter_side,
            x_bin.label("x"),
            y_bin.label("y"),
            func.count(Pitch.pitch_id).label("batted_balls"),
            func.count(Pitch.estimated_woba).label("xwoba_count"),
            func.sum(Pitch.estimated_woba).label("xwoba_sum"),
            func.count(Pitch.exit_velocity).label("ev_count"),
            func.sum(Pitch.exit_velocity).label("ev_sum"),
            func.sum(
                case((Pitch.exit_velocity >= 95, 1), else_=0)
            ).label("hard_hit_count"),
        )
        .select_from(Pitch)
        .join(Game, Game.game_pk == Pitch.game_pk)
        .where(*conditions, *_eligible_contact())
        .group_by(Pitch.pitch_type, Pitch.batter_side, x_bin, y_bin)
        .order_by(Pitch.pitch_type, Pitch.batter_side, y_bin, x_bin)
    )
    if throwing_hand is not None:
        statement = statement.join(Player, Player.mlb_id == Pitch.pitcher_id).where(
            func.upper(Player.throws) == throwing_hand
        )

    return [
        {
            "pitch_type": row["pitch_type"],
            "batter_side": row["batter_side"],
            "x": int(row["x"]),
            "y": int(row["y"]),
            "batted_balls": int(row["batted_balls"]),
            "xwoba_count": int(row["xwoba_count"]),
            "xwoba_sum": float(row["xwoba_sum"] or 0),
            "ev_count": int(row["ev_count"]),
            "ev_sum": float(row["ev_sum"] or 0),
            "hard_hit_count": int(row["hard_hit_count"] or 0),
        }
        for row in db.session.execute(statement).mappings()
    ]


def build_location_performance(
    pitcher_id: int, filters: PitchFilters, throwing_hand: str | None
) -> dict[str, Any]:
    """Return filter-matched pitcher and same-hand league contact samples.

    The league reference includes all loaded pitchers of the *same throwing
    hand* (including the selected pitcher) in identical season, date, count,
    home/away, pitch-type, and batter-side filters. A team filter is
    intentionally NOT applied to the league reference.
    """
    hand = (throwing_hand or "").upper()
    pitcher_rows = _aggregate(pitch_filter_conditions(filters, pitcher_id=pitcher_id))
    league_filters = replace(filters, pitcher=None, team=None)
    league_rows = (
        _aggregate(pitch_filter_conditions(league_filters), throwing_hand=hand)
        if hand in ("R", "L")
        else []
    )

    pitch_counts: dict[str, int] = {}
    for row in pitcher_rows:
        code = row["pitch_type"]
        pitch_counts[code] = pitch_counts.get(code, 0) + row["batted_balls"]

    return {
        "pitcher_throws": hand if hand in ("R", "L") else None,
        "pitch_types": [
            {"pitch_type": code, "pitch_name": PITCH_NAME_MAP.get(code, code)}
            for code in sorted(pitch_counts, key=lambda code: (-pitch_counts[code], code))
        ],
        "batter_sides": [
            side for side in ("R", "L") if any(row["batter_side"] == side for row in pitcher_rows)
        ],
        "pitcher_bins": pitcher_rows,
        "league_bins": league_rows,
        "min_pitcher_contacts": MIN_PITCHER_CONTACTS,
        "min_league_contacts": MIN_LEAGUE_CONTACTS,
        "strike_zone": {"left": -STRIKE_HALF_WIDTH_FT, "right": STRIKE_HALF_WIDTH_FT},
        "league_ignores_team_filter": bool(filters.team),
        "reference_scope": "All loaded MLB pitchers of the same throwing hand",
    }
