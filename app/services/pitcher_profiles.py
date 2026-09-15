"""Database-backed pitcher profile aggregation for API and page consumers."""

from __future__ import annotations

from typing import Any

from sqlalchemy import and_, func, or_, select
from sqlalchemy.engine import RowMapping

from app.extensions import db
from app.models import Game, Pitch, Player
from app.services.database_queries import pitch_filter_conditions, pitcher_team_expression
from app.services.filters import PitchFilters
from app.services.pitch_data import PITCH_NAME_MAP


class PitcherNotFoundError(LookupError):
    """Raised when the requested MLB player ID does not exist."""

    def __init__(self, pitcher_id: int):
        super().__init__(f"Pitcher {pitcher_id} was not found.")
        self.pitcher_id = pitcher_id


class NoMatchingPitchesError(LookupError):
    """Raised when a known player has no pitches under the active filters."""

    def __init__(self, pitcher_id: int, filters: PitchFilters):
        super().__init__("No pitches matched the supplied pitcher and filters.")
        self.pitcher_id = pitcher_id
        self.query = filters.to_dict()


def _count_where(*criteria):
    return func.count(Pitch.pitch_id).filter(*criteria)


def _location_known():
    return or_(
        Pitch.zone.is_not(None),
        and_(
            Pitch.plate_x.is_not(None),
            Pitch.plate_z.is_not(None),
            Pitch.strike_zone_bottom.is_not(None),
            Pitch.strike_zone_top.is_not(None),
        ),
    )


def _metric_columns() -> list[Any]:
    location_known = _location_known()
    event_recorded = and_(Pitch.events.is_not(None), Pitch.events != "")
    event_name = func.lower(Pitch.events)
    return [
        func.count(Pitch.pitch_id).label("pitch_count"),
        _count_where(Pitch.is_strike.is_(True)).label("strikes"),
        _count_where(Pitch.is_swing.is_(True)).label("swings"),
        _count_where(Pitch.is_whiff.is_(True)).label("whiffs"),
        _count_where(Pitch.is_csw.is_(True)).label("csw"),
        _count_where(location_known).label("location_tracked"),
        _count_where(and_(location_known, Pitch.is_in_zone.is_(True))).label("in_zone"),
        _count_where(and_(location_known, Pitch.is_in_zone.is_(False))).label("out_of_zone"),
        _count_where(Pitch.is_chase.is_(True)).label("chases"),
        _count_where(Pitch.exit_velocity.is_not(None)).label("batted_balls"),
        _count_where(Pitch.is_hard_hit.is_(True)).label("hard_hits"),
        _count_where(event_recorded).label("plate_appearances"),
        _count_where(event_name.in_(("strikeout", "strikeout_double_play"))).label("strikeouts"),
        _count_where(event_name.in_(("walk", "intent_walk"))).label("walks"),
        func.avg(Pitch.velocity).label("avg_velocity"),
        func.max(Pitch.velocity).label("max_velocity"),
        func.avg(Pitch.spin_rate).label("avg_spin"),
        func.avg(Pitch.horizontal_break_inches).label("horizontal_break"),
        func.avg(Pitch.vertical_break_inches).label("vertical_break"),
        func.avg(Pitch.release_extension).label("release_extension"),
        func.avg(Pitch.exit_velocity).label("avg_exit_velocity"),
        func.avg(Pitch.estimated_woba).label("xwoba_on_contact"),
    ]


def _integer(row: RowMapping, field: str) -> int:
    return int(row[field] or 0)


def _rounded(value: Any, digits: int = 1) -> float | None:
    return None if value is None else round(float(value), digits)


def _rate(numerator: int, denominator: int) -> float | None:
    return None if denominator == 0 else round(100 * numerator / denominator, 1)


def _performance_metrics(row: RowMapping) -> dict[str, Any]:
    pitches = _integer(row, "pitch_count")
    swings = _integer(row, "swings")
    location_tracked = _integer(row, "location_tracked")
    out_of_zone = _integer(row, "out_of_zone")
    batted_balls = _integer(row, "batted_balls")
    plate_appearances = _integer(row, "plate_appearances")
    return {
        "avg_velocity": _rounded(row["avg_velocity"]),
        "max_velocity": _rounded(row["max_velocity"]),
        "avg_spin": _rounded(row["avg_spin"]),
        "horizontal_break": _rounded(row["horizontal_break"]),
        "vertical_break": _rounded(row["vertical_break"]),
        "release_extension": _rounded(row["release_extension"]),
        "strike_pct": _rate(_integer(row, "strikes"), pitches),
        "swing_pct": _rate(swings, pitches),
        "whiff_pct": _rate(_integer(row, "whiffs"), swings),
        "csw_pct": _rate(_integer(row, "csw"), pitches),
        "zone_pct": _rate(_integer(row, "in_zone"), location_tracked),
        "chase_pct": _rate(_integer(row, "chases"), out_of_zone),
        "hard_hit_pct": _rate(_integer(row, "hard_hits"), batted_balls),
        "strikeout_pct": _rate(_integer(row, "strikeouts"), plate_appearances),
        "walk_pct": _rate(_integer(row, "walks"), plate_appearances),
        "avg_exit_velocity": _rounded(row["avg_exit_velocity"]),
        "xwoba_on_contact": _rounded(row["xwoba_on_contact"], 3),
    }


def _sample(row: RowMapping) -> dict[str, Any]:
    return {
        "pitches": _integer(row, "pitch_count"),
        "games": _integer(row, "games"),
        "plate_appearances": _integer(row, "plate_appearances"),
        "swings": _integer(row, "swings"),
        "batted_balls": _integer(row, "batted_balls"),
        "location_tracked_pitches": _integer(row, "location_tracked"),
        "out_of_zone_pitches": _integer(row, "out_of_zone"),
        "first_game_date": row["first_game_date"].isoformat(),
        "last_game_date": row["last_game_date"].isoformat(),
    }


def _arsenal_rows(conditions: list[Any], total_pitches: int) -> list[dict[str, Any]]:
    statement = (
        select(Pitch.pitch_type, Pitch.pitch_name, *_metric_columns())
        .select_from(Pitch)
        .join(Game, Game.game_pk == Pitch.game_pk)
        .where(*conditions)
        .group_by(Pitch.pitch_type, Pitch.pitch_name)
        .order_by(func.count(Pitch.pitch_id).desc(), Pitch.pitch_type)
    )
    arsenal = []
    for row in db.session.execute(statement).mappings():
        pitch_count = _integer(row, "pitch_count")
        arsenal.append(
            {
                "pitch_type": row["pitch_type"],
                "pitch_name": row["pitch_name"]
                or PITCH_NAME_MAP.get(row["pitch_type"], row["pitch_type"]),
                "pitch_count": pitch_count,
                "usage_pct": _rate(pitch_count, total_pitches),
                **_performance_metrics(row),
            }
        )
    return arsenal


def _platoon_rows(conditions: list[Any]) -> list[dict[str, Any]]:
    statement = (
        select(Pitch.batter_side, *_metric_columns())
        .select_from(Pitch)
        .join(Game, Game.game_pk == Pitch.game_pk)
        .where(*conditions, Pitch.batter_side.in_(("R", "L")))
        .group_by(Pitch.batter_side)
    )
    rows = []
    for row in db.session.execute(statement).mappings():
        rows.append(
            {
                "batter_side": row["batter_side"],
                "label": "vs RHH" if row["batter_side"] == "R" else "vs LHH",
                "pitch_count": _integer(row, "pitch_count"),
                "plate_appearances": _integer(row, "plate_appearances"),
                **_performance_metrics(row),
            }
        )
    return sorted(rows, key=lambda row: (row["batter_side"] != "R", row["batter_side"]))


def list_pitchers(filters: PitchFilters) -> list[dict[str, Any]]:
    """Return database pitchers and stable MLB IDs for UI selection."""
    conditions = pitch_filter_conditions(filters)
    if filters.pitcher:
        conditions.append(Player.player_name.icontains(filters.pitcher, autoescape=True))

    team = pitcher_team_expression().label("team")
    statement = (
        select(
            Player.mlb_id,
            Player.player_name,
            Player.throws,
            team,
            func.count(Pitch.pitch_id).label("pitch_count"),
            func.count(func.distinct(Pitch.game_pk)).label("games"),
            func.min(Game.game_date).label("first_game_date"),
            func.max(Game.game_date).label("last_game_date"),
        )
        .select_from(Player)
        .join(Pitch, Pitch.pitcher_id == Player.mlb_id)
        .join(Game, Game.game_pk == Pitch.game_pk)
        .where(*conditions)
        .group_by(Player.mlb_id, Player.player_name, Player.throws, team)
    )

    pitchers: dict[int, dict[str, Any]] = {}
    for row in db.session.execute(statement).mappings():
        pitcher = pitchers.setdefault(
            row["mlb_id"],
            {
                "mlb_id": row["mlb_id"],
                "name": row["player_name"],
                "throws": row["throws"],
                "teams": [],
                "pitch_count": 0,
                "games": 0,
                "first_game_date": row["first_game_date"].isoformat(),
                "last_game_date": row["last_game_date"].isoformat(),
            },
        )
        if row["team"] and row["team"] not in pitcher["teams"]:
            pitcher["teams"].append(row["team"])
        pitcher["pitch_count"] += int(row["pitch_count"])
        pitcher["games"] += int(row["games"])
        first_date = row["first_game_date"].isoformat()
        last_date = row["last_game_date"].isoformat()
        pitcher["first_game_date"] = min(pitcher["first_game_date"], first_date)
        pitcher["last_game_date"] = max(pitcher["last_game_date"], last_date)

    for pitcher in pitchers.values():
        pitcher["teams"].sort()
    return sorted(
        pitchers.values(),
        key=lambda pitcher: ((pitcher["name"] or "").casefold(), pitcher["mlb_id"]),
    )


def build_pitcher_profile(pitcher_id: int, filters: PitchFilters) -> dict[str, Any]:
    """Build a filtered pitcher profile using database-side aggregations."""
    player = db.session.get(Player, pitcher_id)
    if player is None:
        raise PitcherNotFoundError(pitcher_id)

    conditions = pitch_filter_conditions(filters, pitcher_id=pitcher_id)
    overview_statement = (
        select(
            *_metric_columns(),
            func.count(func.distinct(Pitch.game_pk)).label("games"),
            func.min(Game.game_date).label("first_game_date"),
            func.max(Game.game_date).label("last_game_date"),
        )
        .select_from(Pitch)
        .join(Game, Game.game_pk == Pitch.game_pk)
        .where(*conditions)
    )
    overview = db.session.execute(overview_statement).mappings().one()
    total_pitches = _integer(overview, "pitch_count")
    if total_pitches == 0:
        raise NoMatchingPitchesError(pitcher_id, filters)

    team_statement = (
        select(pitcher_team_expression().label("team"))
        .select_from(Pitch)
        .join(Game, Game.game_pk == Pitch.game_pk)
        .where(*conditions)
        .distinct()
    )
    teams = sorted(
        team for team in db.session.scalars(team_statement) if team is not None and team.strip()
    )

    return {
        "pitcher": {
            "mlb_id": player.mlb_id,
            "name": player.player_name,
            "throws": player.throws,
            "teams": teams,
        },
        "query": filters.to_dict(),
        "sample": _sample(overview),
        "overall": _performance_metrics(overview),
        "arsenal": _arsenal_rows(conditions, total_pitches),
        "platoon_splits": _platoon_rows(conditions),
        "definitions": {
            "rate_unit": "percent",
            "whiff_pct": "whiffs divided by swings",
            "chase_pct": "swings outside the strike zone divided by tracked pitches outside",
            "zone_pct": "in-zone pitches divided by pitches with tracked locations",
            "hard_hit_pct": "batted balls at least 95 mph divided by tracked batted balls",
            "xwoba_on_contact": "average Statcast estimated wOBA on tracked batted balls",
        },
    }
