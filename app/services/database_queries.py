"""Reusable SQLAlchemy conditions for database-backed pitch queries."""

from __future__ import annotations

from sqlalchemy import case, func
from sqlalchemy.sql.elements import ColumnElement

from app.models import Game, Pitch
from app.services.filters import PitchFilters


def pitcher_team_expression():
    """Return the pitcher's team from the batting half and game teams."""
    inning_half = func.lower(Pitch.inning_half)
    return case(
        (inning_half == "top", Game.home_team),
        (inning_half.in_(("bot", "bottom")), Game.away_team),
        else_=None,
    )


def pitch_filter_conditions(
    filters: PitchFilters, *, pitcher_id: int | None = None
) -> list[ColumnElement[bool]]:
    """Translate canonical filters into SQL conditions shared by profile queries."""
    conditions: list[ColumnElement[bool]] = []
    if pitcher_id is not None:
        conditions.append(Pitch.pitcher_id == pitcher_id)
    if filters.team:
        conditions.append(func.upper(pitcher_team_expression()) == filters.team)
    if filters.pitch_types:
        conditions.append(Pitch.pitch_type.in_(filters.pitch_types))
    if filters.batter_sides:
        conditions.append(Pitch.batter_side.in_(filters.batter_sides))
    if filters.season is not None:
        conditions.append(Game.season == filters.season)
    if filters.date_from is not None:
        conditions.append(Game.game_date >= filters.date_from)
    if filters.date_to is not None:
        conditions.append(Game.game_date <= filters.date_to)
    if filters.balls is not None:
        conditions.append(Pitch.balls == filters.balls)
    if filters.strikes is not None:
        conditions.append(Pitch.strikes == filters.strikes)
    if filters.home_away == "home":
        conditions.append(func.lower(Pitch.inning_half) == "top")
    elif filters.home_away == "away":
        conditions.append(func.lower(Pitch.inning_half).in_(("bot", "bottom")))
    return conditions
