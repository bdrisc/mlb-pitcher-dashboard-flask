"""Savant-anchored pitcher run values adjusted for Statcast expected contact.

The observed value is the existing Savant-verified context-neutral pitch run value.
Expected value changes only the batted-ball component, using the season's
FanGraphs wOBA scale to convert the observed/expected wOBA gap into runs.
This is a custom contact-adjusted xRV, not an official Savant xRV statistic.
"""

from __future__ import annotations

from sqlalchemy import and_, case, func, or_

from app.models import Game, Pitch

# FanGraphs Guts! wOBAScale (2023-2026); no estimated fallback for other seasons.
# https://www.fangraphs.com/tools/guts?type=cn
WOBA_SCALES = {
    2023: 1.204,
    2024: 1.242,
    2025: 1.232,
    2026: 1.259,
}

CONTACT_DESCRIPTIONS = ("hit_into_play", "hit_into_play_no_out", "hit_into_play_score")
# Nonstandard PA endings are not interchangeable with a normal hit/out in wOBA.
UNSUPPORTED_CONTACT_EVENTS = (
    "sac_bunt",
    "sac_bunt_double_play",
    "catcher_interf",
    "truncated_pa",
)


def expected_run_value_columns():
    """Return paired totals and transparent missing-data counts for a filtered query.

    Pitcher xRV = pitcher RV + (observed wOBA - Statcast contact xwOBA) / wOBAScale.
    The paired actual/expected populations are identical. A contact play with
    missing source fields is *not* silently scored at its observed run value.
    """
    description = func.lower(func.coalesce(Pitch.description, ""))
    event = func.lower(func.coalesce(Pitch.events, ""))
    physical = and_(
        Pitch.pitch_type.notin_(("", "UN")),
        description.notin_(("automatic_ball", "automatic_strike")),
    )
    has_actual_rv = and_(physical, Pitch.delta_run_expectancy.is_not(None))
    is_batted_ball = description.in_(CONTACT_DESCRIPTIONS)

    woba_scale = case(
        *((Game.season == season, scale) for season, scale in WOBA_SCALES.items()),
        else_=None,
    )
    observed_woba = func.coalesce(Pitch.savant_woba_numerator, Pitch.woba_value)
    usable_contact = and_(
        is_batted_ball,
        event != "",
        event.notin_(UNSUPPORTED_CONTACT_EVENTS),
        Pitch.estimated_woba.between(0, 3),
        observed_woba.between(0, 3),
        woba_scale.is_not(None),
    )
    matched = and_(has_actual_rv, or_(~is_batted_ball, usable_contact))
    actual_pitcher_rv = -Pitch.delta_run_expectancy
    paired_actual = case((matched, actual_pitcher_rv), else_=None)
    paired_expected = case(
        (
            and_(matched, is_batted_ball),
            actual_pitcher_rv + (observed_woba - Pitch.estimated_woba) / woba_scale,
        ),
        (matched, actual_pitcher_rv),
        else_=None,
    )
    # SQL NULLs in a missing Statcast estimate are genuinely unscored contact.
    missing_contact = and_(has_actual_rv, is_batted_ball, ~func.coalesce(usable_contact, False))
    return [
        func.count(Pitch.pitch_id).filter(matched).label("xrv_scored_pitches"),
        func.sum(paired_actual).label("xrv_paired_actual"),
        func.sum(paired_expected).label("xrv_paired_expected"),
        func.count(Pitch.pitch_id).filter(missing_contact).label("xrv_missing_contact"),
        func.count(Pitch.pitch_id)
        .filter(missing_contact, event.in_(UNSUPPORTED_CONTACT_EVENTS))
        .label("xrv_unsupported_contact"),
        func.count(Pitch.pitch_id)
        .filter(physical, Pitch.delta_run_expectancy.is_(None))
        .label("xrv_missing_actual"),
        func.count(Pitch.pitch_id)
        .filter(has_actual_rv, is_batted_ball, woba_scale.is_(None))
        .label("xrv_unknown_scale"),
    ]
