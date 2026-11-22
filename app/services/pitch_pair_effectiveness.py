"""Observed results of genuinely consecutive pitch-type pairs within one PA.

Only the *second* pitch must match the dashboard filters. The previous
pitch comes from the real unfiltered at-bat, so selecting a pitch type or
count never fabricates new adjacency or removes a valid predecessor.

This table is descriptive: an observed result after Pitch A is not proof
that Pitch A caused the result on Pitch B.
"""

from __future__ import annotations

from sqlalchemy import and_, func, or_, select
from sqlalchemy.orm import aliased

from app.extensions import db
from app.models import Game, Pitch
from app.services.database_queries import pitch_filter_conditions
from app.services.pitch_data import PITCH_NAME_MAP

# These definitions follow the profile's existing Whiff%, CSW%, and
# terminal-PA xwOBA handling, including foul tips and missed bunts.
SWING_DESCRIPTIONS = (
    "swinging_strike",
    "swinging_strike_blocked",
    "missed_bunt",
    "foul",
    "foul_tip",
    "foul_bunt",
    "bunt_foul_tip",
    "hit_into_play",
)
WHIFF_DESCRIPTIONS = (
    "swinging_strike",
    "swinging_strike_blocked",
    "foul_tip",
    "missed_bunt",
)
EXCLUDED_XWOBA_PA_EVENTS = (
    "intent_walk",
    "sac_bunt",
    "sac_bunt_double_play",
    "catcher_interf",
    "truncated_pa",
)
SMALL_PAIR_SAMPLE = 30


def _rate(numerator: int, denominator: int) -> float | None:
    return round(100 * numerator / denominator, 1) if denominator else None


def build_pitch_pair_effectiveness(pitcher_id: int, filters) -> dict:
    """Group consecutive physical pitch pairs by ordered A → B pitch types.

    xwOBA uses eligible PA-ending outcomes on B only (NOT all B pitches,
    and NOT xwOBA on contact). Missing eligible xwOBA or pitch-level RV
    never becomes zero: the corresponding rate is withheld unless its
    full eligible denominator has tracked values.
    """
    previous = aliased(Pitch, name="previous_pair_pitch")
    description = func.lower(func.coalesce(Pitch.description, ""))
    previous_description = func.lower(func.coalesce(previous.description, ""))
    event = func.lower(func.coalesce(Pitch.events, ""))
    swing = description.in_(SWING_DESCRIPTIONS)
    whiff = description.in_(WHIFF_DESCRIPTIONS)
    eligible_xwoba_pa = and_(
        event != "",
        event.notin_(EXCLUDED_XWOBA_PA_EVENTS),
    )
    valid_pair = (
        Pitch.pitch_type.notin_(("", "UN")),
        previous.pitch_type.notin_(("", "UN")),
        description.notin_(("automatic_ball", "automatic_strike")),
        previous_description.notin_(("automatic_ball", "automatic_strike")),
    )
    stmt = (
        select(
            previous.pitch_type.label("pitch_a"),
            Pitch.pitch_type.label("pitch_b"),
            func.count(Pitch.pitch_id).label("pair_count"),
            func.count(Pitch.pitch_id).filter(swing).label("swing_count"),
            func.count(Pitch.pitch_id).filter(whiff).label("whiff_count"),
            func.count(Pitch.pitch_id)
            .filter(or_(description == "called_strike", whiff))
            .label("csw_count"),
            func.count(Pitch.pitch_id).filter(eligible_xwoba_pa).label("xwoba_eligible_pa"),
            func.count(Pitch.estimated_woba)
            .filter(eligible_xwoba_pa)
            .label("xwoba_scored_pa"),
            func.sum(Pitch.estimated_woba)
            .filter(eligible_xwoba_pa)
            .label("xwoba_sum"),
            func.count(Pitch.delta_run_expectancy).label("rv_scored_pitches"),
            func.sum(Pitch.delta_run_expectancy).label("rv_against_sum"),
        )
        .select_from(Pitch)
        .join(Game, Game.game_pk == Pitch.game_pk)
        .join(
            previous,
            and_(
                previous.game_pk == Pitch.game_pk,
                previous.pitcher_id == Pitch.pitcher_id,
                previous.batter_id == Pitch.batter_id,
                previous.at_bat_number == Pitch.at_bat_number,
                previous.pitch_number == Pitch.pitch_number - 1,
            ),
        )
        .where(*pitch_filter_conditions(filters, pitcher_id=pitcher_id), *valid_pair)
        .group_by(previous.pitch_type, Pitch.pitch_type)
        .order_by(func.count(Pitch.pitch_id).desc(), previous.pitch_type, Pitch.pitch_type)
    )
    pairs = []
    previous_types = set()
    for row in db.session.execute(stmt).mappings():
        a, b = row["pitch_a"], row["pitch_b"]
        n = int(row["pair_count"])
        swings = int(row["swing_count"])
        whiffs = int(row["whiff_count"])
        csw = int(row["csw_count"])
        pa = int(row["xwoba_eligible_pa"])
        scored_pa = int(row["xwoba_scored_pa"])
        scored_rv = int(row["rv_scored_pitches"])
        # Paired calculations remain exactly aligned with the profile's
        # pitcher-oriented RV sign and its per-100 physical-pitch denominator.
        xwoba = (
            round(float(row["xwoba_sum"]) / pa, 3)
            if pa and scored_pa == pa and row["xwoba_sum"] is not None
            else None
        )
        rv_100 = (
            round(-float(row["rv_against_sum"]) * 100 / n, 1)
            if n and scored_rv == n and row["rv_against_sum"] is not None
            else None
        )
        previous_types.add(a)
        pairs.append(
            {
                "pitch_a": a,
                "pitch_b": b,
                "pitch_a_name": PITCH_NAME_MAP.get(a, a),
                "pitch_b_name": PITCH_NAME_MAP.get(b, b),
                "pair_count": n,
                "small_sample": n < SMALL_PAIR_SAMPLE,
                "swing_count": swings,
                "whiff_count": whiffs,
                "whiff_pct": _rate(whiffs, swings),
                "csw_count": csw,
                "csw_pct": _rate(csw, n),
                "xwoba_eligible_pa": pa,
                "xwoba_scored_pa": scored_pa,
                "xwoba_against": xwoba,
                "rv_scored_pitches": scored_rv,
                "run_value_per_100": rv_100,
            }
        )

    return {
        "method": "consecutive_same_pa_second_pitch_outcomes_v1",
        "filter_pitch": "second",
        "total_pairs": sum(pair["pair_count"] for pair in pairs),
        "small_sample_threshold": SMALL_PAIR_SAMPLE,
        "previous_pitch_types": [
            {"pitch_type": code, "pitch_name": PITCH_NAME_MAP.get(code, code)}
            for code in sorted(previous_types)
        ],
        "pairs": pairs,
    }
