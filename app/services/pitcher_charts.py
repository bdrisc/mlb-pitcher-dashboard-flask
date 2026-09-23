"""Filtered database payloads for the Savant Card's Plotly charts."""

from __future__ import annotations

from collections import defaultdict
from typing import Any

from sqlalchemy import select

from app.extensions import db
from app.models import Game, Pitch, Player
from app.services.database_queries import pitch_filter_conditions
from app.services.filters import PitchFilters
from app.services.pitch_data import PITCH_NAME_MAP
from app.services.pitcher_profiles import NoMatchingPitchesError, PitcherNotFoundError

MAX_SCATTER_POINTS = 6_000


def _rounded(value: Any, digits: int = 1) -> float | None:
    return None if value is None else round(float(value), digits)


def _rate(numerator: int, denominator: int) -> float | None:
    return None if denominator == 0 else round(100 * numerator / denominator, 1)


def _sample_points(points: list[dict[str, Any]]) -> dict[str, Any]:
    """Cap dense browser scatter plots while preserving the full aggregation sample."""
    available = len(points)
    if available <= MAX_SCATTER_POINTS:
        returned = points
    else:
        step = available / MAX_SCATTER_POINTS
        returned = [points[int(index * step)] for index in range(MAX_SCATTER_POINTS)]
    return {
        "available_points": available,
        "returned_points": len(returned),
        "truncated": available > len(returned),
        "points": returned,
    }


def _pitch_order(rows: list[dict[str, Any]]) -> list[tuple[str, str]]:
    counts: dict[tuple[str, str], int] = defaultdict(int)
    for row in rows:
        key = (row["pitch_type"], row["pitch_name"])
        counts[key] += 1
    return sorted(counts, key=lambda key: (-counts[key], key[0]))


def _movement_payload(rows: list[dict[str, Any]], throws: str | None) -> dict[str, Any]:
    horizontal_multiplier = -1 if (throws or "").upper() == "R" else 1
    points = [
        {
            "pitch_type": row["pitch_type"],
            "pitch_name": row["pitch_name"],
            # Normalize the horizontal axis by pitcher handedness so arm-side
            # movement is positive and glove-side movement is negative.
            "horizontal_break": _rounded(row["horizontal_break"] * horizontal_multiplier),
            "vertical_break": _rounded(row["vertical_break"]),
            "velocity": _rounded(row["velocity"]),
            "spin_rate": _rounded(row["spin_rate"], 0),
        }
        for row in rows
        if row["horizontal_break"] is not None and row["vertical_break"] is not None
    ]
    return _sample_points(points)


def _release_payload(rows: list[dict[str, Any]]) -> dict[str, Any]:
    points = [
        {
            "pitch_type": row["pitch_type"],
            "pitch_name": row["pitch_name"],
            "release_pos_x": _rounded(row["release_pos_x"], 2),
            "release_pos_z": _rounded(row["release_pos_z"], 2),
            "release_extension": _rounded(row["release_extension"], 2),
            "game_date": row["game_date"].isoformat(),
        }
        for row in rows
        if row["release_pos_x"] is not None and row["release_pos_z"] is not None
    ]
    return _sample_points(points)


def _location_payload(rows: list[dict[str, Any]]) -> dict[str, Any]:
    eligible = [row for row in rows if row["plate_x"] is not None and row["plate_z"] is not None]
    points = [
        {
            "pitch_type": row["pitch_type"],
            "pitch_name": row["pitch_name"],
            "plate_x": _rounded(row["plate_x"], 2),
            "plate_z": _rounded(row["plate_z"], 2),
            "count": f"{row['balls']}-{row['strikes']}",
            "description": row["description"],
        }
        for row in eligible
    ]
    tops = [float(row["strike_zone_top"]) for row in eligible if row["strike_zone_top"]]
    bottoms = [float(row["strike_zone_bottom"]) for row in eligible if row["strike_zone_bottom"]]
    payload = _sample_points(points)
    payload["strike_zone"] = {
        "left": -0.83,
        "right": 0.83,
        "bottom": _rounded(sum(bottoms) / len(bottoms), 2) if bottoms else 1.5,
        "top": _rounded(sum(tops) / len(tops), 2) if tops else 3.5,
    }
    return payload


def _velocity_trend(rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    groups: dict[tuple[Any, str, str], dict[str, Any]] = {}
    for row in rows:
        if row["velocity"] is None:
            continue
        key = (row["game_date"], row["pitch_type"], row["pitch_name"])
        group = groups.setdefault(
            key,
            {
                "values": [],
                "game_date": row["game_date"],
                "pitch_type": row["pitch_type"],
                "pitch_name": row["pitch_name"],
            },
        )
        group["values"].append(float(row["velocity"]))

    trend = []
    for group in groups.values():
        values = group.pop("values")
        trend.append(
            {
                **group,
                "game_date": group["game_date"].isoformat(),
                "pitch_count": len(values),
                "avg_velocity": _rounded(sum(values) / len(values)),
                "min_velocity": _rounded(min(values)),
                "max_velocity": _rounded(max(values)),
            }
        )
    return sorted(trend, key=lambda row: (row["game_date"], row["pitch_type"]))


def _usage_by_count(rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    totals: dict[str, int] = defaultdict(int)
    groups: dict[tuple[str, str, str], int] = defaultdict(int)
    for row in rows:
        count = f"{row['balls']}-{row['strikes']}"
        totals[count] += 1
        groups[(count, row["pitch_type"], row["pitch_name"])] += 1

    count_order = [f"{balls}-{strikes}" for balls in range(4) for strikes in range(3)]
    order_lookup = {count: index for index, count in enumerate(count_order)}
    payload = [
        {
            "count": count,
            "pitch_type": pitch_type,
            "pitch_name": pitch_name,
            "pitch_count": pitch_count,
            "usage_pct": _rate(pitch_count, totals[count]),
        }
        for (count, pitch_type, pitch_name), pitch_count in groups.items()
    ]
    return sorted(payload, key=lambda row: (order_lookup[row["count"]], row["pitch_type"]))


def build_pitcher_chart_data(pitcher_id: int, filters: PitchFilters) -> dict[str, Any]:
    """Return five chart-ready datasets for one filtered pitcher sample."""
    player = db.session.get(Player, pitcher_id)
    if player is None:
        raise PitcherNotFoundError(pitcher_id)

    conditions = pitch_filter_conditions(filters, pitcher_id=pitcher_id)
    statement = (
        select(
            Pitch.pitch_id,
            Game.game_date,
            Pitch.pitch_type,
            Pitch.pitch_name,
            Pitch.balls,
            Pitch.strikes,
            Pitch.zone,
            Pitch.velocity,
            Pitch.spin_rate,
            Pitch.horizontal_break_inches.label("horizontal_break"),
            Pitch.vertical_break_inches.label("vertical_break"),
            Pitch.release_extension,
            Pitch.release_pos_x,
            Pitch.release_pos_z,
            Pitch.plate_x,
            Pitch.plate_z,
            Pitch.strike_zone_top,
            Pitch.strike_zone_bottom,
            Pitch.description,
        )
        .select_from(Pitch)
        .join(Game, Game.game_pk == Pitch.game_pk)
        .where(*conditions)
        .order_by(Game.game_date, Pitch.game_pk, Pitch.at_bat_number, Pitch.pitch_number)
    )
    rows = []
    for row in db.session.execute(statement).mappings():
        item = dict(row)
        item["pitch_name"] = item["pitch_name"] or PITCH_NAME_MAP.get(
            item["pitch_type"], item["pitch_type"]
        )
        rows.append(item)

    if not rows:
        raise NoMatchingPitchesError(pitcher_id, filters)

    return {
        "pitcher_id": pitcher_id,
        "query": filters.to_dict(),
        "sample": {"pitches": len(rows), "scatter_point_limit": MAX_SCATTER_POINTS},
        "charts": {
            "movement": _movement_payload(rows, player.throws),
            "velocity_trend": {"rows": _velocity_trend(rows)},
            "release_point": _release_payload(rows),
            "location": _location_payload(rows),
            "usage_by_count": {"rows": _usage_by_count(rows)},
        },
    }
