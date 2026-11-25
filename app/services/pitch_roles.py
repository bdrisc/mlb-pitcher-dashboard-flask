"""Descriptive arsenal roles; shared immutable full-league percentile reference."""

from __future__ import annotations

import json
from bisect import bisect_left, bisect_right
from functools import lru_cache
from hashlib import sha256
from math import isfinite
from pathlib import Path

from app.services.filters import COUNT_GROUPS

VERSION = 1
REFERENCE_DIR = Path(__file__).resolve().parents[2] / "data"
MIN_PEERS = 20
# metric, label, minimum denominator
ROLES = (
    ("first_pitch_strike_pct", "Get Ahead", 60),
    ("whiff_pct", "Swing & Miss", 80),
    ("chase_pct", "Chase", 100),
    ("putaway_pct", "Put Away", 60),
    ("gb_pct", "Ground Ball", 40),
    ("run_value_per_100", "RV/100", 150),
    ("expected_run_value_per_100", "xRV/100", 150),
)
COUNTS = tuple((b, s) for b in range(4) for s in range(3))
ROLE_FIELDS = (
    "physical_pitch_count",
    "role_regular_pitches",
    "first_pitch_opportunities",
    "first_pitch_strikes",
    "swings",
    "whiffs",
    "out_of_zone",
    "chases",
    "putaway_pitches",
    "putaway_strikeouts",
    "gb_count",
    "fb_count",
    "ld_count",
    "pu_count",
    "run_value_denominator",
    "run_value_pitches",
    "run_value_against",
    "xrv_scored_pitches",
    "xrv_paired_expected",
    "xrv_eligible_contact",
    "xrv_scored_contact",
)


def role_values(row):
    """Use unrounded sufficient statistics from the existing SQL definitions."""

    def n(key):
        return int(row[key] or 0)

    def cell(num, den, minimum, coverage=True):
        value = 100 * float(num) / den if num is not None and den else None
        return {
            "value": value,
            "sample": den,
            "minimum": minimum,
            "qualified": bool(
                value is not None and isfinite(value) and den >= minimum and coverage
            ),
        }

    rv_n = n("run_value_denominator")
    rv_scored = n("run_value_pitches")
    x_n = n("xrv_scored_pitches")
    contact = n("xrv_eligible_contact")
    classified = sum(n(k) for k in ("gb_count", "fb_count", "ld_count", "pu_count"))
    rv = row["run_value_against"]
    regular = n("physical_pitch_count") == n("role_regular_pitches")
    result = {
        "first_pitch_strike_pct": cell(
            n("first_pitch_strikes"), n("first_pitch_opportunities"), 60
        ),
        "whiff_pct": cell(n("whiffs"), n("swings"), 80),
        "chase_pct": cell(n("chases"), n("out_of_zone"), 100),
        "putaway_pct": cell(n("putaway_strikeouts"), n("putaway_pitches"), 60),
        "gb_pct": cell(n("gb_count"), classified, 40),
        "run_value_per_100": cell(
            -float(rv) if rv is not None and rv_n == rv_scored else None, rv_n, 150
        ),
        "expected_run_value_per_100": cell(
            row["xrv_paired_expected"],
            x_n,
            150,
            coverage=bool(
                rv_n
                and x_n / rv_n >= 0.95
                and (not contact or n("xrv_scored_contact") / contact >= 0.95)
            ),
        ),
    }
    if not regular:
        for metric in result.values():
            metric["qualified"] = False
    return result


def count_key(pairs):
    return ",".join(f"{b}-{s}" for b, s in sorted(pairs))


def count_masks():
    masks = {COUNTS}
    masks.update(tuple(sorted(p)) for p in COUNT_GROUPS.values())
    masks.update(((b, s),) for b, s in COUNTS)
    masks.update(tuple(p for p in COUNTS if p[0] == b) for b in range(4))
    masks.update(tuple(p for p in COUNTS if p[1] == s) for s in range(3))
    return sorted(masks)


def filter_count_key(filters):
    pairs = [
        p
        for p in COUNTS
        if (filters.balls is None or p[0] == filters.balls)
        and (filters.strikes is None or p[1] == filters.strikes)
        and (not filters.count_pairs or p in filters.count_pairs)
    ]
    return count_key(pairs)


def reference_path(season):
    return REFERENCE_DIR / f"league_pitch_roles_{season}.json"


@lru_cache(maxsize=8)
def _load(path, mtime_ns):
    data = Path(path).read_bytes()
    payload = json.loads(data)
    if payload.get("version") != VERSION:
        raise ValueError("Incorrect pitch role reference version")
    if (
        payload.get("pitchers", 0) < 750
        or payload.get("physical_pitches", 0) < 650000
        or payload.get("games", 0) < 2400
    ):
        raise ValueError("Incomplete MLB reference")
    distributions = payload.get("distributions")
    if not isinstance(distributions, dict) or not distributions:
        raise ValueError("Missing pitch role distributions")
    for values in distributions.values():
        if (
            not isinstance(values, list)
            or not all(isinstance(v, (int, float)) and isfinite(v) for v in values)
            or values != sorted(values)
        ):
            raise ValueError("Invalid pitch role distribution")
    # Git may convert LF to CRLF on Windows; hash the same reference bytes
    # after normalizing line endings, without changing parsed distributions.
    return payload, sha256(data.replace(b"\r\n", b"\n")).hexdigest()


def peer_key(pitch_type, hand, side, counts, metric):
    return "|".join((pitch_type, hand, side, counts, metric))


def percentile(value, peers):
    """Midrank empirical percentile; identical observations receive identical ranks."""
    if len(peers) < MIN_PEERS:
        return None
    # SQL sums can differ at machine precision across aggregation orders.
    epsilon = 1e-10
    return round(
        100
        * (bisect_left(peers, value - epsilon) + bisect_right(peers, value + epsilon))
        / (2 * len(peers)),
        1,
    )


def build_pitch_roles(arsenal, filters, hand):
    side = filters.batter_sides[0] if len(filters.batter_sides) == 1 else "ALL"
    counts = filter_count_key(filters)
    reference, digest = None, None
    if filters.season is not None:
        path = reference_path(filters.season)
        try:
            reference, digest = _load(str(path), path.stat().st_mtime_ns)
            if reference["season"] != filters.season:
                reference, digest = None, None
        except (OSError, ValueError, KeyError, TypeError):
            pass
    rows = []
    for metric, label, minimum in ROLES:
        cells = []
        for pitch in arsenal:
            code = pitch["pitch_type"]
            raw = pitch["role_values"][metric]
            peers = (
                reference["distributions"].get(peer_key(code, hand, side, counts, metric), [])
                if reference and hand in ("L", "R") and code not in ("", "UN", None)
                else []
            )
            pctl = percentile(raw["value"], peers) if raw["qualified"] else None
            cells.append(
                {
                    "pitch_type": code,
                    **raw,
                    "percentile": pctl,
                    "peer_count": len(peers),
                    "status": (
                        "no_opportunities"
                        if raw["value"] is None
                        else "not_qualified"
                        if not raw["qualified"]
                        else "reference_unavailable"
                        if not reference
                        else "insufficient_peers"
                        if pctl is None
                        else "qualified"
                    ),
                }
            )
        qualified = [c for c in cells if c["qualified"] and c["pitch_type"] not in ("", "UN", None)]
        ranked = [c for c in qualified if c["percentile"] is not None]

        # Preserve ties instead of arbitrary pitch-order tie breaking.
        def winners(items, key):
            if not items:
                return []
            best = max(c[key] for c in items)
            return [c["pitch_type"] for c in items if c[key] == best]

        rows.append(
            {
                "metric": metric,
                "label": label,
                "minimum": minimum,
                "cells": cells,
                "most_effective": winners(qualified, "value"),
                "best_vs_peers": winners(ranked, "percentile"),
            }
        )
    return {
        "season": filters.season,
        "pitcher_hand": hand,
        "batter_side": side,
        "count_scope": counts,
        "reference_sha256": digest,
        "reference_available": reference is not None,
        "reference_through": reference.get("through") if reference else None,
        "minimum_peers": MIN_PEERS,
        "rows": rows,
    }
