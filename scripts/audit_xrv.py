"""Read-only, reproducible cohort audit for contact-adjusted xRV.

Usage:
    python -m scripts.audit_xrv --season 2026

This uses the dashboard's *same SQL scoring expressions* rather than a second
hand-written xRV implementation. The July 1 split is fixed before scoring.
"""

from __future__ import annotations

import argparse
import json
import math
from datetime import date
from statistics import fmean, stdev

from sqlalchemy import and_, case, func, select

from app import create_app
from app.extensions import db
from app.models import Game, Pitch
from app.services.expected_run_value import WOBA_SCALES, expected_run_value_columns
from app.services.future_season_references import approved_weights


def _corr(left, right):
    if len(left) < 3:
        return None
    x = fmean(left)
    y = fmean(right)
    cross = sum((a - x) * (b - y) for a, b in zip(left, right, strict=True))
    ssx = sum((a - x) ** 2 for a in left)
    ssy = sum((b - y) ** 2 for b in right)
    return cross / math.sqrt(ssx * ssy) if ssx and ssy else None


def _round(number, digits=4):
    return None if number is None else round(number, digits)


def audit_season(season, min_half_pitches=300):
    physical = and_(
        Pitch.pitch_type.notin_(("", "UN")),
        func.lower(func.coalesce(Pitch.description, "")).notin_(
            ("automatic_ball", "automatic_strike")
        ),
    )
    half = case(
        (Game.game_date < date(season, 7, 1), "H1"),
        else_="H2",
    )
    query = (
        select(
            Pitch.pitcher_id,
            half.label("half"),
            func.count(Pitch.pitch_id).filter(physical).label("physical"),
            func.sum(Pitch.delta_run_expectancy).label("rv_against"),
            *expected_run_value_columns(),
        )
        .join(Game, Game.game_pk == Pitch.game_pk)
        .where(Game.season == season)
        .group_by(Pitch.pitcher_id, half)
    )
    rows = db.session.execute(query).mappings().all()
    observed = sum(int(row["xrv_scored_contact"]) for row in rows)
    total = sum(int(row["xrv_eligible_contact"]) for row in rows)
    weighted = sum(float(row["xrv_contact_observed_woba_sum"] or 0) for row in rows)
    expected = sum(float(row["xrv_contact_expected_woba_sum"] or 0) for row in rows)
    physical_total = sum(int(row["physical"]) for row in rows)
    paired_total = sum(int(row["xrv_scored_pitches"]) for row in rows)
    output = {
        "season": season,
        "scope": "pitchers actually present in the connected database",
        "pitchers": len({row["pitcher_id"] for row in rows}),
        "physical_pitches": physical_total,
        "matched_pitches": paired_total,
        "contact_total": total,
        "contact_scored": observed,
        "pitch_coverage_pct": _round(paired_total * 100 / physical_total, 2)
        if physical_total
        else None,
        "contact_coverage_pct": _round(observed * 100 / total, 2) if total else None,
        "observed_contact_woba": _round(weighted / observed, 5) if observed else None,
        "expected_contact_woba": _round(expected / observed, 5) if observed else None,
        "contact_woba_residual": _round((weighted - expected) / observed, 5) if observed else None,
        "source": "Savant context-neutral RV + Statcast EV/LA xwOBA + FanGraphs Guts",
        "woba_scale": (
            approved_weights().get(season, (None,))[0] if season >= 2027 else WOBA_SCALES.get(season)
        ),
        "comparison": "Paired RV/100 and xRV/100; full Savant RV/100 has a different denominator",
    }
    halves = {}
    for row in rows:
        n = int(row["physical"])
        matched = int(row["xrv_scored_pitches"])
        if not n or not matched or row["rv_against"] is None:
            continue
        halves.setdefault(row["pitcher_id"], {})[row["half"]] = {
            "n": n,
            "actual": -100 * float(row["rv_against"]) / n,
            "expected": 100 * float(row["xrv_paired_expected"]) / matched,
        }
    eligible = [
        (pair["H1"], pair["H2"])
        for pair in halves.values()
        if all(part in pair for part in ("H1", "H2"))
        and pair["H1"]["n"] >= min_half_pitches
        and pair["H2"]["n"] >= min_half_pitches
    ]
    if len(eligible) < 3:
        output["split_half"] = {
            "status": "insufficient sample",
            "pitchers": len(eligible),
            "cutoff": f"{season}-07-01",
        }
        return output
    future_actual = [second["actual"] for _, second in eligible]
    first_actual = [first["actual"] for first, _ in eligible]
    first_expected = [first["expected"] for first, _ in eligible]
    err_rv = [abs(a - b) for a, b in zip(first_actual, future_actual, strict=True)]
    err_xrv = [abs(a - b) for a, b in zip(first_expected, future_actual, strict=True)]
    gains = [a - b for a, b in zip(err_rv, err_xrv, strict=True)]
    mean_gain = fmean(gains)
    standard_error = stdev(gains) / math.sqrt(len(gains))
    output["split_half"] = {
        "status": "descriptive, not proof of superiority",
        "cutoff": f"{season}-07-01",
        "pitchers": len(eligible),
        "min_pitches_per_half": min_half_pitches,
        "correlation_first_rv_to_future_rv": _round(_corr(first_actual, future_actual)),
        "correlation_first_xrv_to_future_rv": _round(_corr(first_expected, future_actual)),
        "mae_first_rv_to_future_rv": _round(fmean(err_rv)),
        "mae_first_xrv_to_future_rv": _round(fmean(err_xrv)),
        "mae_gain_rv_minus_xrv": _round(mean_gain),
        "mae_gain_se": _round(standard_error),
        "mae_gain_approx_95pct_ci": [
            _round(mean_gain - 1.96 * standard_error),
            _round(mean_gain + 1.96 * standard_error),
        ],
        "pitchers_with_smaller_xrv_error": sum(a > b for a, b in zip(err_rv, err_xrv, strict=True)),
        "pitchers_with_smaller_rv_error": sum(a < b for a, b in zip(err_rv, err_xrv, strict=True)),
    }
    return output


def main():
    parser = argparse.ArgumentParser(description="Audit xRV calibration and temporal holdout.")
    parser.add_argument("--season", type=int, default=2026)
    parser.add_argument("--min-half-pitches", type=int, default=300)
    args = parser.parse_args()
    app = create_app()
    with app.app_context():
        report = audit_season(args.season, args.min_half_pitches)
    print(json.dumps(report, indent=2))


if __name__ == "__main__":
    main()
