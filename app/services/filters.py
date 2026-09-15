"""Shared query-string parsing and validation for pitch-analysis endpoints."""

from __future__ import annotations

import re
from dataclasses import dataclass
from datetime import date
from typing import Any

from werkzeug.datastructures import MultiDict

from app.services.pitch_data import PITCH_NAME_MAP

MIN_STATCAST_SEASON = 2008
ALLOWED_FILTERS = {
    "pitcher",
    "team",
    "pitch_type",
    "batter_side",
    "season",
    "date_from",
    "date_to",
    "balls",
    "strikes",
    "home_away",
}
PITCH_TYPE_ALIASES = {
    **{code.casefold(): code for code in PITCH_NAME_MAP},
    **{name.casefold(): code for code, name in PITCH_NAME_MAP.items()},
}
SIDE_ALIASES = {"r": "R", "right": "R", "l": "L", "left": "L"}
HOME_AWAY_ALIASES = {"h": "home", "home": "home", "a": "away", "away": "away"}


class FilterValidationError(ValueError):
    """Raised when one or more query parameters are invalid."""

    def __init__(self, errors: dict[str, list[str]]):
        super().__init__("Invalid query parameters.")
        self.errors = errors


@dataclass(frozen=True)
class PitchFilters:
    """Canonical, typed filters shared by every pitch-analysis endpoint."""

    pitcher: str | None = None
    team: str | None = None
    pitch_types: tuple[str, ...] = ()
    batter_sides: tuple[str, ...] = ()
    season: int | None = None
    date_from: date | None = None
    date_to: date | None = None
    balls: int | None = None
    strikes: int | None = None
    home_away: str | None = None

    def to_dict(self) -> dict[str, Any]:
        """Serialize only active filters for API responses and logging."""
        values: dict[str, Any] = {
            "pitcher": self.pitcher,
            "team": self.team,
            "pitch_type": list(self.pitch_types) or None,
            "batter_side": list(self.batter_sides) or None,
            "season": self.season,
            "date_from": self.date_from.isoformat() if self.date_from else None,
            "date_to": self.date_to.isoformat() if self.date_to else None,
            "balls": self.balls,
            "strikes": self.strikes,
            "home_away": self.home_away,
        }
        return {key: value for key, value in values.items() if value is not None}

    def dataframe_kwargs(self) -> dict[str, Any]:
        """Translate the canonical object into the in-memory store's interface."""
        return {
            "pitcher": self.pitcher,
            "team": self.team,
            "pitch_types": self.pitch_types,
            "batter_sides": self.batter_sides,
            "season": self.season,
            "date_from": self.date_from,
            "date_to": self.date_to,
            "balls": self.balls,
            "strikes": self.strikes,
            "home_away": self.home_away,
        }


def _add_error(errors: dict[str, list[str]], field: str, message: str) -> None:
    errors.setdefault(field, []).append(message)


def _single_value(
    args: MultiDict[str, str], field: str, errors: dict[str, list[str]]
) -> str | None:
    values = args.getlist(field)
    if len(values) > 1:
        _add_error(errors, field, "must be supplied only once")
        return None
    if not values:
        return None
    value = values[0].strip()
    return value or None


def _list_values(args: MultiDict[str, str], field: str) -> list[str]:
    values: list[str] = []
    for raw_value in args.getlist(field):
        values.extend(part.strip() for part in raw_value.split(",") if part.strip())
    return list(dict.fromkeys(values))


def _bounded_integer(
    value: str | None,
    *,
    field: str,
    minimum: int,
    maximum: int,
    errors: dict[str, list[str]],
) -> int | None:
    if value is None:
        return None
    try:
        parsed = int(value)
    except ValueError:
        _add_error(errors, field, "must be an integer")
        return None
    if not minimum <= parsed <= maximum:
        _add_error(errors, field, f"must be between {minimum} and {maximum}")
        return None
    return parsed


def _date_value(value: str | None, *, field: str, errors: dict[str, list[str]]) -> date | None:
    if value is None:
        return None
    try:
        return date.fromisoformat(value)
    except ValueError:
        _add_error(errors, field, "must use YYYY-MM-DD format")
        return None


def _enum_values(
    values: list[str],
    *,
    field: str,
    aliases: dict[str, str],
    errors: dict[str, list[str]],
) -> tuple[str, ...]:
    normalized: list[str] = []
    invalid: list[str] = []
    for value in values:
        result = aliases.get(value.casefold())
        if result is None:
            invalid.append(value)
        elif result not in normalized:
            normalized.append(result)
    if invalid:
        _add_error(errors, field, "contains unsupported value(s): " + ", ".join(invalid))
    return tuple(normalized)


def parse_pitch_filters(
    args: MultiDict[str, str],
    *,
    require_pitcher: bool = False,
    forbidden: frozenset[str] = frozenset(),
) -> PitchFilters:
    """Validate Flask request arguments and return one canonical filter object."""
    errors: dict[str, list[str]] = {}

    for field in sorted(set(args) - ALLOWED_FILTERS):
        _add_error(errors, field, "is not a supported filter")
    for field in sorted(set(args) & forbidden):
        _add_error(errors, field, "is not allowed for this endpoint")

    pitcher = _single_value(args, "pitcher", errors)
    if pitcher and len(pitcher) > 120:
        _add_error(errors, "pitcher", "must be 120 characters or fewer")
    if require_pitcher and not pitcher:
        _add_error(errors, "pitcher", "is required")

    team = _single_value(args, "team", errors)
    if team:
        team = team.upper()
        if not re.fullmatch(r"[A-Z]{2,3}", team):
            _add_error(errors, "team", "must be a two- or three-letter team code")

    pitch_types = _enum_values(
        _list_values(args, "pitch_type"),
        field="pitch_type",
        aliases=PITCH_TYPE_ALIASES,
        errors=errors,
    )
    batter_sides = _enum_values(
        _list_values(args, "batter_side"),
        field="batter_side",
        aliases=SIDE_ALIASES,
        errors=errors,
    )

    season = _bounded_integer(
        _single_value(args, "season", errors),
        field="season",
        minimum=MIN_STATCAST_SEASON,
        maximum=date.today().year,
        errors=errors,
    )
    date_from = _date_value(
        _single_value(args, "date_from", errors), field="date_from", errors=errors
    )
    date_to = _date_value(_single_value(args, "date_to", errors), field="date_to", errors=errors)
    if date_from and date_to and date_from > date_to:
        _add_error(errors, "date_range", "date_from must be on or before date_to")

    balls = _bounded_integer(
        _single_value(args, "balls", errors),
        field="balls",
        minimum=0,
        maximum=3,
        errors=errors,
    )
    strikes = _bounded_integer(
        _single_value(args, "strikes", errors),
        field="strikes",
        minimum=0,
        maximum=2,
        errors=errors,
    )

    home_away_value = _single_value(args, "home_away", errors)
    home_away = None
    if home_away_value:
        home_away = HOME_AWAY_ALIASES.get(home_away_value.casefold())
        if home_away is None:
            _add_error(errors, "home_away", "must be home or away")

    if errors:
        raise FilterValidationError(errors)

    return PitchFilters(
        pitcher=pitcher,
        team=team,
        pitch_types=pitch_types,
        batter_sides=batter_sides,
        season=season,
        date_from=date_from,
        date_to=date_to,
        balls=balls,
        strikes=strikes,
        home_away=home_away,
    )
