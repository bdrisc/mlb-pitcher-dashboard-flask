"""Immutable, verified full-league location contact statistics for 2026."""

from __future__ import annotations

import gzip
import json
from collections import defaultdict
from decimal import Decimal
from functools import lru_cache
from hashlib import sha256
from math import isfinite
from pathlib import Path
from typing import Any

from app.services.filters import PitchFilters
from app.services.future_season_references import artifact

REFERENCE_SEASON = 2026
REFERENCE_SHA256 = "eb09bc3ce164730186ce699c7c3443150a8339626dff1775ec6639b8a9d3ec99"
REFERENCE_PATH = Path(__file__).resolve().parents[2] / "data" / "league_location_2026.json.gz"
FIELDS = (
    "date",
    "balls",
    "strikes",
    "venue",
    "hand",
    "pitch_type",
    "batter_side",
    "x",
    "y",
    "batted_balls",
    "xwoba_count",
    "xwoba_sum",
    "ev_count",
    "ev_sum",
    "hard_hit_count",
)


@lru_cache(maxsize=1)
def _load_reference() -> dict[str, tuple[tuple[Any, ...], ...]]:
    """Fail closed for a missing or altered 2026 reference; never use cohort data."""
    compressed = REFERENCE_PATH.read_bytes()
    if sha256(compressed).hexdigest() != REFERENCE_SHA256:
        raise ValueError("2026 location reference checksum mismatch")
    payload = json.loads(gzip.decompress(compressed))
    if (
        payload["version"] != 1
        or payload["season"] != REFERENCE_SEASON
        or tuple(payload["fields"]) != FIELDS
        or payload["physical_coverage"] != [868, 714114, 714114, 2429]
        or payload["game_types"] != {"R": 714114}
        or len(payload["rows"]) != 82639
        or sum(row[9] for row in payload["rows"]) != 93353
    ):
        raise ValueError("Invalid verified 2026 location reference metadata")
    grouped: dict[str, list[tuple[Any, ...]]] = {"L": [], "R": []}
    keys = set()
    for row in payload["rows"]:
        key = tuple(row[:9])
        if key in keys:
            raise ValueError("Duplicate location reference key")
        keys.add(key)
        row[11] = Decimal(row[11])
        row[13] = Decimal(row[13])
        grouped[row[4]].append(tuple(row))
    return {hand: tuple(rows) for hand, rows in grouped.items()}


def _rollup(filters, rows):
    """Roll up unrounded counts and sums, matching the existing SQL filters."""
    start = filters.date_from.isoformat() if filters.date_from else None
    end = filters.date_to.isoformat() if filters.date_to else None
    pairs = filters.count_pairs
    totals = defaultdict(lambda: [0, 0, Decimal(0), 0, Decimal(0), 0])
    for day, balls, strikes, venue, _, code, side, x, y, *values in rows:
        if (start and day < start) or (end and day > end):
            continue
        if filters.home_away and venue != filters.home_away:
            continue
        if filters.pitch_types and code not in filters.pitch_types:
            continue
        if filters.batter_sides and side not in filters.batter_sides:
            continue
        if filters.balls is not None and balls != filters.balls:
            continue
        if filters.strikes is not None and strikes != filters.strikes:
            continue
        if pairs and (balls, strikes) not in pairs:
            continue
        total = totals[code, side, x, y]
        for index, value in enumerate(values):
            total[index] += value
    return [
        {
            "pitch_type": code,
            "batter_side": side,
            "x": x,
            "y": y,
            "batted_balls": n,
            "xwoba_count": wn,
            "xwoba_sum": float(ws),
            "ev_count": en,
            "ev_sum": float(es),
            "hard_hit_count": hh,
        }
        for (code, side, x, y), (n, wn, ws, en, es, hh) in sorted(
            totals.items(), key=lambda item: (item[0][0], item[0][1], item[0][3], item[0][2])
        )
    ]


@lru_cache(maxsize=64)
def shared_league_bins(filters: PitchFilters, hand: str) -> list[dict[str, Any]]:
    if filters.season != REFERENCE_SEASON:
        raise ValueError("Unsupported shared location reference season")
    return _rollup(filters, _load_reference()[hand])


@lru_cache(maxsize=4)
def _load_future(path, checksum, season, start, through, coverage):
    payload = json.loads(gzip.decompress(Path(path).read_bytes()))
    if (
        payload["version"] != 1
        or payload["season"] != season
        or tuple(payload["fields"]) != FIELDS
        or tuple(payload["physical_coverage"]) != coverage
        or payload["start"] != start
        or payload["through"] != through
        or payload["game_types"] != {"R": coverage[1]}
    ):
        raise ValueError("Future location reference metadata mismatch.")
    grouped = {"L": [], "R": []}
    keys = set()
    for row in payload["rows"]:
        day, balls, strikes, venue, hand, code, side, x, y, n, wn, ws, en, es, hh = row
        key = tuple(row[:9])
        ws, es = Decimal(ws), Decimal(es)
        if (
            key in keys
            or not start <= day <= through
            or balls not in range(4)
            or strikes not in range(3)
            or venue not in ("home", "away")
            or hand not in grouped
            or side not in ("L", "R")
            or not code
            or x not in range(3)
            or y not in range(3)
            or any(type(v) is not int for v in (n, wn, en, hh))
            or not 0 <= wn <= n
            or not 0 <= hh <= en <= n
            or n <= 0
            or not all(isfinite(v) and v >= 0 for v in (ws, es))
        ):
            raise ValueError("Invalid future location reference row.")
        keys.add(key)
        grouped[hand].append((*key, n, wn, ws, en, es, hh))
    if not keys or sum(row[9] for rows in grouped.values() for row in rows) > coverage[1]:
        raise ValueError("Invalid location contact coverage.")
    return grouped


def future_league_bins(filters, hand):
    approved = artifact(filters.season, "location")
    if approved is None:
        return None
    path, entry = approved
    start, through = entry["start"], entry["through"]
    if filters.date_to and filters.date_to.isoformat() > through:
        return None
    if filters.date_from and filters.date_from.isoformat() < start:
        return None
    try:
        rows = _load_future(
            str(path),
            entry["artifacts"]["location"]["sha256"],
            filters.season,
            start,
            through,
            tuple(entry["coverage"]),
        )
        return _rollup(filters, rows[hand]), through
    except (OSError, ValueError, TypeError, KeyError, ArithmeticError, EOFError):
        return None
