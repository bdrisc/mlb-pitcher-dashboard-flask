"""Database-backed pitcher profile aggregation for API and page consumers."""

from __future__ import annotations

from decimal import ROUND_HALF_UP, Decimal
from typing import Any

from sqlalchemy import and_, func, or_, select
from sqlalchemy.engine import RowMapping

from app.extensions import db
from app.models import Game, Pitch, Player
from app.services.database_queries import pitch_filter_conditions, pitcher_team_expression
from app.services.fangraphs_stuff import profile_grades
from app.services.filters import PitchFilters
from app.services.pitch_data import PITCH_NAME_MAP
from app.services.pitch_separation import build_pitch_separation


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
    description = func.lower(Pitch.description)
    swing = description.in_(
        (
            "swinging_strike",
            "swinging_strike_blocked",
            "missed_bunt",
            "foul",
            "foul_tip",
            "foul_bunt",
            "bunt_foul_tip",
            "hit_into_play",
        )
    )
    whiff = description.in_(
        ("swinging_strike", "swinging_strike_blocked", "foul_tip", "missed_bunt")
    )
    # SwStr% counts only full swings and misses, independently of the existing
    # Savant-style whiff grouping (which also includes foul tips/missed bunts).
    swinging_strike = description.in_(("swinging_strike", "swinging_strike_blocked"))
    physical_pitch = func.coalesce(description, "").notin_(("automatic_ball", "automatic_strike"))
    strike = description.in_(
        (
            "called_strike",
            "swinging_strike",
            "swinging_strike_blocked",
            "missed_bunt",
            "foul",
            "foul_tip",
            "foul_bunt",
            "bunt_foul_tip",
            "hit_into_play",
        )
    )
    tracked_batted_ball = and_(
        Pitch.batted_ball_type.is_not(None),
        Pitch.batted_ball_type != "",
        Pitch.exit_velocity.is_not(None),
    )
    expected_contact = and_(
        Pitch.batted_ball_type.is_not(None),
        Pitch.batted_ball_type != "",
        Pitch.estimated_woba.is_not(None),
    )
    # Savant supplies expected weights for terminal PA outcomes, including
    # strikeouts (0), unintentional walks and HBP. Nonterminal pitches and
    # outcomes outside the wOBA denominator must not enter this average.
    expected_pa = and_(
        event_recorded,
        event_name.notin_(
            ("intent_walk", "sac_bunt", "sac_bunt_double_play", "catcher_interf", "truncated_pa")
        ),
        Pitch.estimated_woba.is_not(None),
    )
    return [
        func.count(Pitch.pitch_id).label("pitch_count"),
        _count_where(strike).label("strikes"),
        _count_where(swing).label("swings"),
        _count_where(whiff).label("whiffs"),
        _count_where(swinging_strike).label("swinging_strikes"),
        _count_where(physical_pitch).label("swstr_pitches"),
        _count_where(or_(description == "called_strike", whiff)).label("csw"),
        _count_where(location_known).label("location_tracked"),
        _count_where(and_(location_known, Pitch.is_in_zone.is_(True))).label("in_zone"),
        _count_where(and_(location_known, Pitch.is_in_zone.is_(False))).label("out_of_zone"),
        _count_where(Pitch.is_chase.is_(True)).label("chases"),
        _count_where(tracked_batted_ball).label("batted_balls"),
        _count_where(and_(tracked_batted_ball, Pitch.exit_velocity >= 95)).label("hard_hits"),
        _count_where(event_recorded).label("plate_appearances"),
        _count_where(event_name.in_(("strikeout", "strikeout_double_play"))).label("strikeouts"),
        _count_where(event_name.in_(("walk", "intent_walk"))).label("walks"),
        _count_where(
            Pitch.pitch_type.notin_(("", "UN")),
            func.coalesce(func.lower(Pitch.description), "").notin_(
                ("automatic_ball", "automatic_strike")
            ),
        ).label("run_value_denominator"),
        func.sum(Pitch.delta_run_expectancy).label("run_value_against"),
        func.count(Pitch.delta_run_expectancy).label("run_value_pitches"),
        func.avg(Pitch.velocity).label("avg_velocity"),
        func.avg(Pitch.vaa).label("vaa"),
        func.avg(Pitch.expected_vaa).label("expected_vaa"),
        func.avg(Pitch.vaa_adj).label("vaa_adj"),
        func.count(Pitch.vaa_adj).label("vaa_adj_pitch_count"),
        func.avg(Pitch.haa).label("haa"),
        func.avg(Pitch.expected_haa).label("expected_haa"),
        func.avg(Pitch.haaaa).label("haaaa"),
        func.count(Pitch.haaaa).label("haaaa_pitch_count"),
        func.count(Pitch.vaa).label("vaa_pitch_count"),
        func.count(Pitch.haa).label("haa_pitch_count"),
        func.max(Pitch.velocity).label("max_velocity"),
        func.avg(Pitch.spin_rate).label("avg_spin"),
        func.avg(Pitch.horizontal_break_inches).label("horizontal_break"),
        func.avg(Pitch.vertical_break_inches).label("vertical_break"),
        func.avg(Pitch.release_extension).label("release_extension"),
        func.avg(Pitch.exit_velocity).filter(tracked_batted_ball).label("avg_exit_velocity"),
        func.avg(Pitch.estimated_woba).filter(expected_pa).label("xwoba_against"),
        func.avg(Pitch.estimated_woba).filter(expected_contact).label("xwoba_on_contact"),
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
    run_value_pitches = _integer(row, "run_value_pitches")
    run_value_denominator = _integer(row, "run_value_denominator")
    pitcher_run_value = (
        None if row["run_value_against"] is None else -float(row["run_value_against"])
    )
    return {
        "run_value_per_100": (
            None
            if not run_value_pitches or not run_value_denominator
            else float(
                (Decimal(str(round(pitcher_run_value, 9))) * 100 / run_value_denominator).quantize(
                    Decimal("0.1"), rounding=ROUND_HALF_UP
                )
            )
            or 0.0
        ),
        "run_value": _rounded(pitcher_run_value, 3),
        "run_value_pitch_count": run_value_pitches,
        "run_value_denominator": run_value_denominator,
        "run_value_coverage_pct": _rate(run_value_pitches, run_value_denominator),
        "avg_velocity": _rounded(row["avg_velocity"]),
        "vaa": _rounded(row["vaa"]),
        "expected_vaa": _rounded(row["expected_vaa"], 2),
        "vaa_adj": _rounded(row["vaa_adj"], 2),
        "vaa_adj_pitch_count": _integer(row, "vaa_adj_pitch_count"),
        "haa": _rounded(row["haa"]),
        "expected_haa": _rounded(row["expected_haa"], 2),
        "haaaa": _rounded(row["haaaa"], 2),
        "haaaa_pitch_count": _integer(row, "haaaa_pitch_count"),
        "vaa_pitch_count": _integer(row, "vaa_pitch_count"),
        "haa_pitch_count": _integer(row, "haa_pitch_count"),
        "max_velocity": _rounded(row["max_velocity"]),
        "avg_spin": _rounded(row["avg_spin"]),
        "horizontal_break": _rounded(row["horizontal_break"]),
        "vertical_break": _rounded(row["vertical_break"]),
        "release_extension": _rounded(row["release_extension"]),
        "strike_pct": _rate(_integer(row, "strikes"), pitches),
        "swing_pct": _rate(swings, pitches),
        "whiff_pct": _rate(_integer(row, "whiffs"), swings),
        "swstr_pct": _rate(_integer(row, "swinging_strikes"), _integer(row, "swstr_pitches")),
        "swinging_strike_count": _integer(row, "swinging_strikes"),
        "swstr_pitch_count": _integer(row, "swstr_pitches"),
        "csw_pct": _rate(_integer(row, "csw"), pitches),
        "zone_pct": _rate(_integer(row, "in_zone"), location_tracked),
        "chase_pct": _rate(_integer(row, "chases"), out_of_zone),
        "hard_hit_pct": _rate(_integer(row, "hard_hits"), batted_balls),
        "strikeout_pct": _rate(_integer(row, "strikeouts"), plate_appearances),
        "walk_pct": _rate(_integer(row, "walks"), plate_appearances),
        "k_minus_bb_pct": _rate(
            _integer(row, "strikeouts") - _integer(row, "walks"), plate_appearances
        ),
        "avg_exit_velocity": _rounded(row["avg_exit_velocity"]),
        "xwoba_against": _rounded(row["xwoba_against"], 3),
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

    stuff = profile_grades(pitcher_id, filters.season)
    arsenal = _arsenal_rows(conditions, total_pitches)
    # FanGraphs' slider category can combine Statcast sliders and sweepers.
    has_sweeper = (
        db.session.scalar(
            select(Pitch.pitch_id)
            .join(Game, Game.game_pk == Pitch.game_pk)
            .where(
                Pitch.pitcher_id == pitcher_id,
                Game.season == filters.season,
                Pitch.pitch_type.in_(("ST", "SV")),
            )
            .limit(1)
        )
        is not None
    )
    ambiguous_slider = has_sweeper and stuff["pitches"].get("ST") is None
    for pitch in arsenal:
        pitch["stuff_plus"] = stuff["pitches"].get(pitch["pitch_type"])
        pitch["location_plus"] = stuff["pitch_location"].get(pitch["pitch_type"])
        pitch["pitching_plus"] = stuff["pitch_pitching"].get(pitch["pitch_type"])
        if ambiguous_slider and pitch["pitch_type"] == "SL":
            for metric in ("stuff_plus", "location_plus", "pitching_plus"):
                pitch[metric] = None
    if ambiguous_slider and stuff["overall"] is not None:
        stuff["message"] += (
            " Slider/sweeper grades are withheld where categories cannot be separated."
        )

    return {
        "fangraphs": stuff,
        "pitcher": {
            "mlb_id": player.mlb_id,
            "name": player.player_name,
            "throws": player.throws,
            "teams": teams,
        },
        "query": filters.to_dict(),
        "sample": _sample(overview),
        "overall": {
            **_performance_metrics(overview),
            "stuff_plus": stuff["overall"],
            "location_plus": stuff["location_plus"],
            "pitching_plus": stuff["pitching_plus"],
        },
        "arsenal": arsenal,
        "pitch_separation": build_pitch_separation(conditions),
        "platoon_splits": _platoon_rows(conditions),
    }
