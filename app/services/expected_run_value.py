"""Contact-adjusted pitcher RV using Savant pitch RV and dated FanGraphs weights.

This is an original contact-adjustment metric, not official Baseball Savant xRV.
The unchanged observed run value is the existing stored Savant-aligned pitch RV.
Both the observed contact wOBA weight and wOBA-to-runs conversion use the SAME
seasonal FanGraphs Guts! coefficients to avoid mixing stale Statcast vintages.
"""

from __future__ import annotations

from sqlalchemy import and_, case, func, or_

from app.models import Game, Pitch

# FanGraphs Guts! wOBA constants, refreshed against the live page on 2026-11-16.
# https://www.fangraphs.com/tools/guts?type=cn
# Values: (wOBAScale, w1B, w2B, w3B, wHR); the 2026 final coefficients
# were revised from an earlier 1.259 / .897 / 1.275 / 1.614 / 2.079.
WOBA_CONSTANTS = {
    2015: (1.251, 0.881, 1.256, 1.594, 2.065),
    2016: (1.212, 0.878, 1.242, 1.569, 2.015),
    2017: (1.185, 0.877, 1.232, 1.552, 1.980),
    2018: (1.226, 0.880, 1.247, 1.578, 2.031),
    2019: (1.157, 0.870, 1.217, 1.529, 1.940),
    2020: (1.185, 0.883, 1.238, 1.558, 1.979),
    2021: (1.209, 0.879, 1.242, 1.568, 2.007),
    2022: (1.259, 0.884, 1.261, 1.601, 2.072),
    2023: (1.204, 0.883, 1.244, 1.569, 2.004),
    2024: (1.242, 0.882, 1.254, 1.590, 2.050),
    2025: (1.232, 0.882, 1.252, 1.584, 2.037),
    2026: (1.238, 0.890, 1.261, 1.596, 2.049),
}
WOBA_SCALES = {year: values[0] for year, values in WOBA_CONSTANTS.items()}

CONTACT_DESCRIPTIONS = ("hit_into_play", "hit_into_play_no_out", "hit_into_play_score")
HIT_EVENTS = ("single", "double", "triple", "home_run")
ZERO_WEIGHT_CONTACT_EVENTS = (
    "field_out",
    "force_out",
    "other_out",
    "fielders_choice",
    "fielders_choice_out",
    "grounded_into_double_play",
    "double_play",
    "triple_play",
    "sac_fly",
    "sac_fly_double_play",
    "field_error",
)
VALID_CONTACT_EVENTS = HIT_EVENTS + ZERO_WEIGHT_CONTACT_EVENTS


def xrv_quality_status(*, scored, physical, contact_total, contact_scored):
    """Describe tracking/sample sufficiency, not future predictive reliability.

    Thresholds are presentation guardrails, NOT learned calibration parameters.
    """
    if not scored:
        return "unavailable"
    if (contact_total >= 30 and contact_scored / contact_total < 0.95) or (
        physical >= 200 and scored / physical < 0.95
    ):
        return "limited_coverage"
    if scored < 300 or contact_total < 30:
        return "small_sample"
    return "descriptive"


def _season_constant(column):
    """Produce a SQL expression returning a Guts constant for Game.season."""
    return case(
        *((Game.season == season, values[column]) for season, values in WOBA_CONSTANTS.items()),
        else_=None,
    )


def expected_run_value_columns():
    """Return paired run-value sums with strict contact and source coverage counts.

    Pitcher xRV = pitcher RV + (observed wOBA weight - contact xwOBA) / wOBAScale.
    Outcome weights come from the same Guts vintage as the seasonal scale.
    Observed pitcher RV uses its original source without reinterpretation.
    """
    description = func.lower(func.coalesce(Pitch.description, ""))
    event = func.lower(func.coalesce(Pitch.events, ""))
    physical = and_(
        Pitch.pitch_type.notin_(("", "UN")),
        description.notin_(("automatic_ball", "automatic_strike")),
    )
    has_actual_rv = and_(physical, Pitch.delta_run_expectancy.is_not(None))
    is_batted_ball = description.in_(CONTACT_DESCRIPTIONS)
    scale = _season_constant(0)
    observed_weight = case(
        (event == "single", _season_constant(1)),
        (event == "double", _season_constant(2)),
        (event == "triple", _season_constant(3)),
        (event == "home_run", _season_constant(4)),
        else_=0.0,
    )
    source_weight = func.coalesce(Pitch.savant_woba_numerator, Pitch.woba_value)
    usable_contact = and_(
        is_batted_ball,
        event.in_(VALID_CONTACT_EVENTS),
        Pitch.estimated_woba.between(0, 3),
        scale.is_not(None),
    )
    matched = and_(has_actual_rv, or_(~is_batted_ball, usable_contact))
    actual_pitcher_rv = -Pitch.delta_run_expectancy
    paired_actual = case((matched, actual_pitcher_rv), else_=None)
    paired_expected = case(
        (
            and_(matched, is_batted_ball),
            actual_pitcher_rv + (observed_weight - Pitch.estimated_woba) / scale,
        ),
        (matched, actual_pitcher_rv),
        else_=None,
    )
    # NULL expected outcomes count as truly missing, not zero-value contact.
    missing_contact = and_(has_actual_rv, is_batted_ball, ~func.coalesce(usable_contact, False))
    different_imported_weight = and_(
        matched,
        is_batted_ball,
        source_weight.is_not(None),
        func.abs(source_weight - observed_weight) > 0.005,
    )
    return [
        func.count(Pitch.pitch_id)
        .filter(has_actual_rv, is_batted_ball)
        .label("xrv_eligible_contact"),
        func.count(Pitch.pitch_id)
        .filter(has_actual_rv, usable_contact)
        .label("xrv_scored_contact"),
        func.sum(observed_weight)
        .filter(has_actual_rv, usable_contact)
        .label("xrv_contact_observed_woba_sum"),
        func.sum(Pitch.estimated_woba)
        .filter(has_actual_rv, usable_contact)
        .label("xrv_contact_expected_woba_sum"),
        func.count(Pitch.pitch_id).filter(matched).label("xrv_scored_pitches"),
        func.sum(paired_actual).label("xrv_paired_actual"),
        func.sum(paired_expected).label("xrv_paired_expected"),
        func.count(Pitch.pitch_id).filter(missing_contact).label("xrv_missing_contact"),
        func.count(Pitch.pitch_id)
        .filter(missing_contact, event.notin_(VALID_CONTACT_EVENTS), event != "")
        .label("xrv_unsupported_contact"),
        func.count(Pitch.pitch_id)
        .filter(physical, Pitch.delta_run_expectancy.is_(None))
        .label("xrv_missing_actual"),
        func.count(Pitch.pitch_id)
        .filter(has_actual_rv, is_batted_ball, scale.is_(None))
        .label("xrv_unknown_scale"),
        func.count(Pitch.pitch_id)
        .filter(different_imported_weight)
        .label("xrv_imported_weight_mismatch"),
    ]
