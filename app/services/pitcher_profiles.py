"""Database-backed pitcher profile aggregation for API and page consumers."""

from __future__ import annotations

from decimal import ROUND_HALF_UP, Decimal
from math import atan2, cos, degrees, hypot, radians, sin, sqrt
from typing import Any

from sqlalchemy import and_, case, func, or_, select
from sqlalchemy.engine import RowMapping

from app.extensions import db
from app.models import Game, Pitch, Player
from app.services.database_queries import pitch_filter_conditions, pitcher_team_expression
from app.services.expected_run_value import expected_run_value_columns, xrv_quality_status
from app.services.expected_woba import full_xwoba_expressions
from app.services.fangraphs_stuff import profile_grades
from app.services.filters import PitchFilters
from app.services.movement_reference import movement_vs_average
from app.services.pitch_data import PITCH_NAME_MAP
from app.services.pitch_pair_effectiveness import build_pitch_pair_effectiveness
from app.services.pitch_roles import build_pitch_roles, role_values
from app.services.pitch_separation import build_pitch_separation
from app.services.pitch_sequencing import build_pitch_transition_matrix
from app.services.pitch_tunneling import add_tunneling_to_separation, build_pitch_tunneling
from app.services.published_pitching import published_references
from app.services.savant_active_spin import published_active_spin
from app.services.woba_refresh import NON_PA_EVENTS


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
    in_zone = and_(location_known, Pitch.is_in_zone.is_(True))
    out_of_zone = and_(location_known, Pitch.is_in_zone.is_(False))
    event_recorded = and_(Pitch.events.is_not(None), Pitch.events != "")
    event_name = func.lower(Pitch.events)
    description = func.lower(Pitch.description)
    actual_pa = and_(event_recorded, event_name.notin_(NON_PA_EVENTS))
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
            "hit_into_play_no_out",
            "hit_into_play_score",
        )
    )
    whiff = description.in_(
        ("swinging_strike", "swinging_strike_blocked", "foul_tip", "missed_bunt")
    )
    # SwStr% counts only full swings and misses, independently of the existing
    # Savant-style whiff grouping (which also includes foul tips/missed bunts).
    swinging_strike = description.in_(("swinging_strike", "swinging_strike_blocked"))
    physical_pitch = func.coalesce(description, "").notin_(("automatic_ball", "automatic_strike"))
    physical_rv_pitch = and_(physical_pitch, Pitch.pitch_type.notin_(("", "UN")))
    # Counts are before the pitch. Automatic calls are not pitches thrown.
    two_strike_pitch = and_(Pitch.strikes == 2, physical_pitch)
    putaway = and_(two_strike_pitch, event_name.in_(("strikeout", "strikeout_double_play")))
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
            "hit_into_play_no_out",
            "hit_into_play_score",
        )
    )
    bbe = description.in_(("hit_into_play", "hit_into_play_no_out", "hit_into_play_score"))
    classified_bbe = and_(bbe, Pitch.launch_speed_angle.between(1, 6))
    batted_ball_kind = func.lower(func.trim(Pitch.batted_ball_type))
    valid_arm_angle = and_(physical_pitch, Pitch.arm_angle.between(0, 90))
    # Evaluate both axes on exactly the same physical pitches.
    joint_release = and_(
        physical_pitch,
        Pitch.release_pos_x.is_not(None),
        Pitch.release_pos_z.is_not(None),
    )
    joint_movement = and_(
        Pitch.arm_angle.is_not(None),
        Pitch.horizontal_break_inches.is_not(None),
        Pitch.vertical_break_inches.is_not(None),
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
    # The speed/angle field is CONTACT-ONLY. Full xwOBA must also account
    # for strikeouts (zero) and Savant's actual BB/HBP outcome weights.
    expected_pa, expected_pa_value = full_xwoba_expressions()
    # Savant xBA: expected hits on tracked batted balls / (tracked AB + strikeouts).
    # Batted balls without a Statcast xBA estimate do not count as zero-hit balls.
    official_ab = and_(
        event_recorded,
        event_name.notin_(
            (
                *NON_PA_EVENTS,
                "walk",
                "intent_walk",
                "hit_by_pitch",
                "sac_fly",
                "sac_fly_double_play",
                "sac_bunt",
                "sac_bunt_double_play",
                "catcher_interf",
            )
        ),
    )
    strikeout_ab = and_(
        official_ab,
        event_name.in_(("strikeout", "strikeout_double_play")),
    )
    scored_batted_ball = and_(
        official_ab,
        event_name.notin_(("strikeout", "strikeout_double_play")),
        Pitch.estimated_ba.is_not(None),
    )
    xba_scored_ab = or_(strikeout_ab, scored_batted_ball)
    # Savant expected total bases on tracked batted balls, with strikeouts
    # counting as zero and missing-contact estimates omitted, as with xBA.
    scored_slg_ball = and_(
        official_ab,
        event_name.notin_(("strikeout", "strikeout_double_play")),
        Pitch.estimated_slg.is_not(None),
    )
    xslg_scored_ab = or_(strikeout_ab, scored_slg_ball)
    return [
        func.count(Pitch.pitch_id).label("pitch_count"),
        _count_where(physical_pitch).label("physical_pitch_count"),
        _count_where(strike).label("strikes"),
        _count_where(physical_pitch, Pitch.balls == 0, Pitch.strikes == 0).label(
            "first_pitch_opportunities"
        ),
        _count_where(strike, physical_pitch, Pitch.balls == 0, Pitch.strikes == 0).label(
            "first_pitch_strikes"
        ),
        _count_where(physical_pitch, Game.game_type == "R").label("role_regular_pitches"),
        _count_where(swing).label("swings"),
        _count_where(whiff).label("whiffs"),
        _count_where(swinging_strike).label("swinging_strikes"),
        _count_where(physical_pitch).label("swstr_pitches"),
        _count_where(two_strike_pitch).label("putaway_pitches"),
        _count_where(putaway).label("putaway_strikeouts"),
        _count_where(or_(description == "called_strike", whiff)).label("csw"),
        _count_where(location_known, physical_pitch).label("location_tracked"),
        _count_where(in_zone, physical_pitch).label("in_zone"),
        _count_where(in_zone, swing).label("zone_swings"),
        _count_where(in_zone, whiff).label("zone_whiffs"),
        _count_where(out_of_zone, physical_pitch).label("out_of_zone"),
        _count_where(out_of_zone, swing).label("out_of_zone_swings"),
        _count_where(out_of_zone, whiff).label("out_of_zone_whiffs"),
        # Recompute against the SAME zone and swing definitions for old and
        # newly imported rows; saved is_chase flags may reflect older rules.
        _count_where(out_of_zone, swing).label("chases"),
        _count_where(tracked_batted_ball).label("batted_balls"),
        _count_where(bbe).label("barrel_bbe_count"),
        _count_where(bbe, batted_ball_kind == "ground_ball").label("gb_count"),
        _count_where(bbe, batted_ball_kind == "fly_ball").label("fb_count"),
        _count_where(bbe, batted_ball_kind == "line_drive").label("ld_count"),
        _count_where(bbe, batted_ball_kind == "popup").label("pu_count"),
        _count_where(and_(bbe, Pitch.barrel_checked.is_(True))).label("barrel_checked_count"),
        _count_where(classified_bbe).label("barrel_classified_count"),
        _count_where(and_(bbe, Pitch.launch_speed_angle == 6)).label("barrel_count"),
        _count_where(and_(tracked_batted_ball, Pitch.exit_velocity >= 95)).label("hard_hits"),
        # Truncated/interrupted at-bats are not completed PA for K%/BB%.
        _count_where(actual_pa).label("plate_appearances"),
        _count_where(event_name.in_(("strikeout", "strikeout_double_play"))).label("strikeouts"),
        _count_where(event_name.in_(("walk", "intent_walk"))).label("walks"),
        _count_where(physical_rv_pitch).label("run_value_denominator"),
        func.sum(Pitch.delta_run_expectancy).filter(physical_rv_pitch).label("run_value_against"),
        func.count(Pitch.delta_run_expectancy).filter(physical_rv_pitch).label("run_value_pitches"),
        *expected_run_value_columns(),
        func.avg(Pitch.velocity).label("avg_velocity"),
        # Official Statcast effective_speed: perceived mph adjusted for release
        # extension only, not location or sequencing. Exclude automatic calls.
        func.avg(Pitch.effective_velocity).filter(physical_pitch).label("avg_effective_velocity"),
        func.count(Pitch.effective_velocity)
        .filter(physical_pitch)
        .label("effective_velocity_pitch_count"),
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
        func.avg(Pitch.arm_angle).filter(valid_arm_angle).label("avg_arm_angle"),
        _count_where(valid_arm_angle).label("arm_angle_pitch_count"),
        func.avg(Pitch.release_pos_z).filter(physical_pitch).label("avg_release_height"),
        func.count(Pitch.release_pos_z).filter(physical_pitch).label("release_height_pitch_count"),
        func.avg(Pitch.release_pos_x).filter(physical_pitch).label("avg_release_side"),
        func.count(Pitch.release_pos_x).filter(physical_pitch).label("release_side_pitch_count"),
        _count_where(joint_release).label("release_point_sd_pitch_count"),
        func.sum(Pitch.release_pos_x).filter(joint_release).label("release_side_sum"),
        func.sum(Pitch.release_pos_z).filter(joint_release).label("release_height_sum"),
        func.sum(Pitch.release_pos_x * Pitch.release_pos_x)
        .filter(joint_release)
        .label("release_side_sum_sq"),
        func.sum(Pitch.release_pos_z * Pitch.release_pos_z)
        .filter(joint_release)
        .label("release_height_sum_sq"),
        func.avg(Pitch.horizontal_break_inches).label("horizontal_break"),
        func.avg(Pitch.vertical_break_inches).label("vertical_break"),
        func.avg(Pitch.arm_angle).filter(joint_movement).label("movement_arm_angle"),
        func.avg(Pitch.horizontal_break_inches).filter(joint_movement).label("movement_joint_hb"),
        func.avg(Pitch.vertical_break_inches).filter(joint_movement).label("movement_joint_ivb"),
        _count_where(joint_movement).label("movement_joint_pitches"),
        func.avg(Pitch.release_extension).filter(physical_pitch).label("release_extension"),
        func.count(Pitch.release_extension)
        .filter(physical_pitch)
        .label("release_extension_pitch_count"),
        func.avg(Pitch.exit_velocity).filter(tracked_batted_ball).label("avg_exit_velocity"),
        _count_where(
            actual_pa,
            or_(Pitch.savant_woba_numerator.is_(None), Pitch.savant_woba_denominator.is_(None)),
        ).label("woba_pending_outcomes"),
        func.sum(Pitch.savant_woba_numerator).filter(actual_pa).label("woba_numerator"),
        func.sum(Pitch.savant_woba_denominator).filter(actual_pa).label("woba_denominator"),
        _count_where(expected_pa).label("xwoba_eligible_pa"),
        func.count(expected_pa_value).filter(expected_pa).label("xwoba_scored_pa"),
        func.sum(expected_pa_value).filter(expected_pa).label("xwoba_sum"),
        func.avg(Pitch.estimated_woba).filter(expected_contact).label("xwoba_on_contact"),
        _count_where(official_ab).label("xba_at_bats"),
        _count_where(xba_scored_ab).label("xba_scored_at_bats"),
        func.sum(Pitch.estimated_ba).filter(scored_batted_ball).label("xba_expected_hits"),
        _count_where(xslg_scored_ab).label("xslg_scored_at_bats"),
        _count_where(scored_slg_ball).label("xslg_scored_contact"),
        func.sum(Pitch.estimated_slg).filter(scored_slg_ball).label("xslg_expected_bases"),
    ]


def _integer(row: RowMapping, field: str) -> int:
    return int(row[field] or 0)


def _rounded(value: Any, digits: int = 1) -> float | None:
    return None if value is None else round(float(value), digits)


def _rate(numerator: int, denominator: int) -> float | None:
    return None if denominator == 0 else round(100 * numerator / denominator, 1)


def _batted_ball_percentages(counts: tuple[int, int, int, int]) -> tuple[float | None, ...]:
    """Distribute tenths of a percent so displayed GB/FB/LD/PU always sum to 100.0."""
    total = sum(counts)
    if not total:
        return (None, None, None, None)

    tenths = [count * 1000 // total for count in counts]
    remaining = 1000 - sum(tenths)
    # Largest-remainder allocation avoids a visible 99.9% or 100.1% total.
    # Tie order is GB, FB, LD, PU for stable results.
    order = sorted(range(4), key=lambda i: (-(counts[i] * 1000 % total), i))
    for index in order[:remaining]:
        tenths[index] += 1
    return tuple(value / 10 for value in tenths)


def _performance_metrics(row: RowMapping) -> dict[str, Any]:
    # Calculate a sample SD from SQL sums so both PostgreSQL and SQLite work.
    # Each component uses the same paired, physical-pitch sample (n >= 2).
    release_count = _integer(row, "release_point_sd_pitch_count")

    def release_component_sd(axis: str) -> float | None:
        if release_count < 2:
            return None
        total = float(row[f"release_{axis}_sum"])
        total_sq = float(row[f"release_{axis}_sum_sq"])
        variance = (total_sq - total * total / release_count) / (release_count - 1)
        return sqrt(max(0.0, variance))

    release_side_sd_ft = release_component_sd("side")
    release_height_sd_ft = release_component_sd("height")
    release_sd_inches = (
        hypot(release_side_sd_ft, release_height_sd_ft) * 12
        if release_side_sd_ft is not None and release_height_sd_ft is not None
        else None
    )
    physical_pitches = _integer(row, "physical_pitch_count")
    swings = _integer(row, "swings")
    location_tracked = _integer(row, "location_tracked")
    out_of_zone = _integer(row, "out_of_zone")
    batted_balls = _integer(row, "batted_balls")
    ball_type_counts = tuple(
        _integer(row, key) for key in ("gb_count", "fb_count", "ld_count", "pu_count")
    )
    gb_pct, fb_pct, ld_pct, pu_pct = _batted_ball_percentages(ball_type_counts)
    ball_type_total = sum(ball_type_counts)
    plate_appearances = _integer(row, "plate_appearances")
    run_value_pitches = _integer(row, "run_value_pitches")
    run_value_denominator = _integer(row, "run_value_denominator")
    pitcher_run_value = (
        None if row["run_value_against"] is None else -float(row["run_value_against"])
    )
    xrv_scored = _integer(row, "xrv_scored_pitches")
    contact_total = _integer(row, "xrv_eligible_contact")
    contact_scored = _integer(row, "xrv_scored_contact")
    contact_coverage = _rate(contact_scored, contact_total)
    xrv_pitch_coverage = _rate(xrv_scored, run_value_denominator)
    xrv_quality = xrv_quality_status(
        scored=xrv_scored,
        physical=run_value_denominator,
        contact_total=contact_total,
        contact_scored=contact_scored,
    )
    paired_actual = row["xrv_paired_actual"]
    paired_expected = row["xrv_paired_expected"]
    rv_minus_xrv = (
        None
        if paired_actual is None or paired_expected is None
        else float(paired_actual) - float(paired_expected)
    )

    def _per_100(value):
        if value is None or not xrv_scored:
            return None
        calculated = Decimal(str(round(float(value), 9))) * 100 / xrv_scored
        return float(calculated.quantize(Decimal("0.1"), rounding=ROUND_HALF_UP))

    xwoba_eligible = _integer(row, "xwoba_eligible_pa")
    xwoba_scored = _integer(row, "xwoba_scored_pa")
    full_xwoba = (
        _rounded(float(row["xwoba_sum"]) / xwoba_eligible, 3)
        if xwoba_eligible and xwoba_eligible == xwoba_scored
        else None
    )

    woba_denom = _integer(row, "woba_denominator")
    woba_pending = _integer(row, "woba_pending_outcomes")
    woba = None
    if woba_denom and not woba_pending:
        total = Decimal(str(round(row["woba_numerator"], 9)))
        woba = float((total / woba_denom).quantize(Decimal("0.001"), rounding=ROUND_HALF_UP))
    xba_at_bats = _integer(row, "xba_at_bats")
    xba_scored_at_bats = _integer(row, "xba_scored_at_bats")
    xba = None
    if xba_scored_at_bats:
        expected_hits = Decimal(str(round(float(row["xba_expected_hits"] or 0), 9)))
        xba = float(
            (expected_hits / xba_scored_at_bats).quantize(Decimal("0.001"), rounding=ROUND_HALF_UP)
        )
    xslg_scored_at_bats = _integer(row, "xslg_scored_at_bats")
    xslg = None
    if xslg_scored_at_bats and (
        _integer(row, "xslg_scored_contact") or xslg_scored_at_bats == xba_at_bats
    ):
        expected_bases = Decimal(str(round(float(row["xslg_expected_bases"] or 0), 9)))
        expected_rate = (expected_bases / xslg_scored_at_bats).quantize(
            Decimal("0.001"), rounding=ROUND_HALF_UP
        )
        xslg = float(expected_rate)
    return {
        "woba_against": woba,
        "xba": xba,
        "xslg": xslg,
        "xslg_at_bats": xba_at_bats,
        "xslg_scored_at_bats": xslg_scored_at_bats,
        "xslg_untracked_at_bats": xba_at_bats - xslg_scored_at_bats,
        "xba_at_bats": xba_at_bats,
        "xba_scored_at_bats": xba_scored_at_bats,
        "xba_untracked_at_bats": xba_at_bats - xba_scored_at_bats,
        "woba_denominator": woba_denom,
        "woba_pending_outcomes": woba_pending,
        "run_value_per_100": (
            None
            if run_value_pitches != run_value_denominator or not run_value_denominator
            else float(
                (Decimal(str(round(pitcher_run_value, 9))) * 100 / run_value_denominator).quantize(
                    Decimal("0.1"), rounding=ROUND_HALF_UP
                )
            )
            or 0.0
        ),
        # Withhold incomplete run-value totals instead of treating missing
        # pitch outcomes as zero or silently diluting RV/100.
        "run_value": (
            _rounded(pitcher_run_value, 3)
            if run_value_denominator and run_value_pitches == run_value_denominator
            else None
        ),
        "run_value_pitch_count": run_value_pitches,
        "run_value_denominator": run_value_denominator,
        "run_value_coverage_pct": _rate(run_value_pitches, run_value_denominator),
        "expected_run_value": _rounded(paired_expected, 3),
        "expected_run_value_per_100": _per_100(paired_expected),
        "paired_actual_run_value": _rounded(paired_actual, 3),
        "paired_actual_run_value_per_100": _per_100(paired_actual),
        "run_value_minus_expected": _rounded(rv_minus_xrv, 3),
        "run_value_minus_expected_per_100": _per_100(rv_minus_xrv),
        "expected_run_value_pitch_count": xrv_scored,
        "expected_run_value_coverage_pct": xrv_pitch_coverage,
        "expected_run_value_contact_count": contact_total,
        "expected_run_value_scored_contact_count": contact_scored,
        "expected_run_value_contact_coverage_pct": contact_coverage,
        "expected_run_value_quality": xrv_quality,
        "expected_run_value_unscored_contact": _integer(row, "xrv_missing_contact"),
        "expected_run_value_unsupported_contact": _integer(row, "xrv_unsupported_contact"),
        "expected_run_value_missing_actual": _integer(row, "xrv_missing_actual"),
        "expected_run_value_unknown_scale": _integer(row, "xrv_unknown_scale"),
        "expected_run_value_imported_weight_mismatch": _integer(
            row, "xrv_imported_weight_mismatch"
        ),
        "avg_velocity": _rounded(row["avg_velocity"]),
        "avg_effective_velocity": _rounded(row["avg_effective_velocity"]),
        "effective_velocity_pitch_count": _integer(row, "effective_velocity_pitch_count"),
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
        "avg_arm_angle": _rounded(row["avg_arm_angle"]),
        "arm_angle_pitch_count": _integer(row, "arm_angle_pitch_count"),
        "avg_release_height": _rounded(row["avg_release_height"], 1),
        "release_height_pitch_count": _integer(row, "release_height_pitch_count"),
        "avg_release_side": _rounded(row["avg_release_side"], 1),
        "release_side_pitch_count": _integer(row, "release_side_pitch_count"),
        "release_point_sd_inches": _rounded(release_sd_inches),
        "release_height_sd_inches": _rounded(
            float(release_height_sd_ft) * 12 if release_height_sd_ft is not None else None
        ),
        "release_side_sd_inches": _rounded(
            float(release_side_sd_ft) * 12 if release_side_sd_ft is not None else None
        ),
        "release_point_sd_pitch_count": _integer(row, "release_point_sd_pitch_count"),
        "horizontal_break": _rounded(row["horizontal_break"]),
        "vertical_break": _rounded(row["vertical_break"]),
        "release_extension": _rounded(row["release_extension"]),
        "release_extension_pitch_count": _integer(row, "release_extension_pitch_count"),
        "physical_pitch_count": physical_pitches,
        "strike_pct": _rate(_integer(row, "strikes"), physical_pitches),
        "swing_pct": _rate(swings, physical_pitches),
        "whiff_pct": _rate(_integer(row, "whiffs"), swings),
        "zone_whiff_pct": _rate(_integer(row, "zone_whiffs"), _integer(row, "zone_swings")),
        "zone_whiff_count": _integer(row, "zone_whiffs"),
        "zone_swing_count": _integer(row, "zone_swings"),
        "out_of_zone_whiff_pct": _rate(
            _integer(row, "out_of_zone_whiffs"), _integer(row, "out_of_zone_swings")
        ),
        "out_of_zone_whiff_count": _integer(row, "out_of_zone_whiffs"),
        "out_of_zone_swing_count": _integer(row, "out_of_zone_swings"),
        "swstr_pct": _rate(_integer(row, "swinging_strikes"), _integer(row, "swstr_pitches")),
        "swinging_strike_count": _integer(row, "swinging_strikes"),
        "swstr_pitch_count": _integer(row, "swstr_pitches"),
        "putaway_pct": _rate(_integer(row, "putaway_strikeouts"), _integer(row, "putaway_pitches")),
        "putaway_strikeout_count": _integer(row, "putaway_strikeouts"),
        "putaway_pitch_count": _integer(row, "putaway_pitches"),
        "csw_pct": _rate(_integer(row, "csw"), physical_pitches),
        "zone_pct": _rate(_integer(row, "in_zone"), location_tracked),
        "chase_pct": _rate(_integer(row, "chases"), out_of_zone),
        "hard_hit_pct": _rate(_integer(row, "hard_hits"), batted_balls),
        "gb_pct": gb_pct,
        "fb_pct": fb_pct,
        "ld_pct": ld_pct,
        "pu_pct": pu_pct,
        "gb_count": ball_type_counts[0],
        "fb_count": ball_type_counts[1],
        "ld_count": ball_type_counts[2],
        "pu_count": ball_type_counts[3],
        "batted_ball_type_count": ball_type_total,
        "batted_ball_type_unclassified": max(
            0, _integer(row, "barrel_bbe_count") - ball_type_total
        ),
        "barrel_pct": (
            _rate(_integer(row, "barrel_count"), _integer(row, "barrel_bbe_count"))
            if (
                _integer(row, "barrel_checked_count") == _integer(row, "barrel_bbe_count")
                and _integer(row, "barrel_classified_count") > 0
            )
            else None
        ),
        "barrel_count": _integer(row, "barrel_count"),
        "barrel_bbe_count": _integer(row, "barrel_bbe_count"),
        "barrel_checked_bbe_count": _integer(row, "barrel_checked_count"),
        "barrel_classified_bbe_count": _integer(row, "barrel_classified_count"),
        "barrel_coverage_pct": _rate(
            _integer(row, "barrel_classified_count"), _integer(row, "barrel_bbe_count")
        ),
        "strikeout_pct": _rate(_integer(row, "strikeouts"), plate_appearances),
        "walk_pct": _rate(_integer(row, "walks"), plate_appearances),
        "k_minus_bb_pct": _rate(
            _integer(row, "strikeouts") - _integer(row, "walks"), plate_appearances
        ),
        "avg_exit_velocity": _rounded(row["avg_exit_velocity"]),
        "xwoba_against": full_xwoba,
        "xwoba_eligible_pa": xwoba_eligible,
        "xwoba_scored_pa": xwoba_scored,
        "xwoba_missing_pa": xwoba_eligible - xwoba_scored,
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


def _arsenal_rows(
    conditions: list[Any], total_pitches: int, season: int | None, hand: str | None
) -> list[dict[str, Any]]:
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
        metrics = _performance_metrics(row)
        roles = role_values(row)
        for key, cell in roles.items():
            cell["display_value"] = metrics.get(
                key,
                _rate(
                    _integer(row, "first_pitch_strikes"), _integer(row, "first_pitch_opportunities")
                ),
            )
        arsenal.append(
            {
                "pitch_type": row["pitch_type"],
                "pitch_name": row["pitch_name"]
                or PITCH_NAME_MAP.get(row["pitch_type"], row["pitch_type"]),
                "pitch_count": pitch_count,
                "usage_pct": _rate(pitch_count, total_pitches),
                **metrics,
                "role_values": roles,
                **movement_vs_average(
                    season=season,
                    pitch_type=row["pitch_type"],
                    throwing_hand=hand,
                    arm_angle=row["movement_arm_angle"],
                    horizontal_break=row["movement_joint_hb"],
                    vertical_break=row["movement_joint_ivb"],
                ),
                "movement_joint_pitches": _integer(row, "movement_joint_pitches"),
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


def _times_through_order_splits(conditions: list[Any], total_pitches: int) -> dict[str, Any]:
    """Filtered performance and pitch-mix splits by Statcast lineup trip.

    Statcast n_thruorder_pitcher is already ingested on every pitch. Group
    fourth and later trips together, without treating missing/zero as first.
    """
    turn = case(
        (Pitch.times_through_order >= 4, 4),
        else_=Pitch.times_through_order,
    )
    physical_pitch = func.coalesce(func.lower(Pitch.description), "").notin_(
        ("automatic_ball", "automatic_strike")
    )
    where = (*conditions, Pitch.times_through_order >= 1, physical_pitch)
    performance_statement = (
        select(turn.label("turn"), *_metric_columns())
        .select_from(Pitch)
        .join(Game, Game.game_pk == Pitch.game_pk)
        .where(*where)
        .group_by(turn)
        .order_by(turn)
    )
    labels = {1: "1st", 2: "2nd", 3: "3rd", 4: "4th+"}
    performance = []
    for row in db.session.execute(performance_statement).mappings():
        number = int(row["turn"])
        metrics = _performance_metrics(row)
        appearances = _integer(row, "plate_appearances")
        performance.append(
            {
                "turn": number,
                "label": labels[number],
                "pitch_count": _integer(row, "pitch_count"),
                "plate_appearances": appearances,
                "small_sample": appearances < 30,
                "strikeout_pct": metrics["strikeout_pct"],
                "walk_pct": metrics["walk_pct"],
                "k_minus_bb_pct": metrics["k_minus_bb_pct"],
                "whiff_pct": metrics["whiff_pct"],
                "xwoba_against": metrics["xwoba_against"],
                "xwoba_eligible_pa": metrics["xwoba_eligible_pa"],
                "xwoba_scored_pa": metrics["xwoba_scored_pa"],
                "run_value_per_100": metrics["run_value_per_100"],
                "avg_velocity": metrics["avg_velocity"],
                "run_value_pitch_count": metrics["run_value_pitch_count"],
                "run_value_denominator": metrics["run_value_denominator"],
            }
        )

    # Pitch mix uses real, tracked pitch types and excludes automatic calls.
    # Its denominator is the sum of valid pitches within each TTO bucket.
    mix_statement = (
        select(
            turn.label("turn"),
            Pitch.pitch_type,
            func.max(Pitch.pitch_name).label("pitch_name"),
            func.count(Pitch.pitch_id).label("pitch_count"),
        )
        .select_from(Pitch)
        .join(Game, Game.game_pk == Pitch.game_pk)
        .where(
            *where,
            physical_pitch,
            Pitch.pitch_type.is_not(None),
            Pitch.pitch_type.notin_(("", "UN")),
        )
        .group_by(turn, Pitch.pitch_type)
        .order_by(turn, func.count(Pitch.pitch_id).desc(), Pitch.pitch_type)
    )
    by_turn: dict[int, list[dict[str, Any]]] = {}
    for row in db.session.execute(mix_statement).mappings():
        number = int(row["turn"])
        pitch_type = row["pitch_type"]
        by_turn.setdefault(number, []).append(
            {
                "pitch_type": pitch_type,
                "pitch_name": row["pitch_name"] or PITCH_NAME_MAP.get(pitch_type, pitch_type),
                "pitch_count": _integer(row, "pitch_count"),
            }
        )
    pitch_mix = []
    for number, pitches in sorted(by_turn.items()):
        total = sum(pitch["pitch_count"] for pitch in pitches)
        pitch_mix.append(
            {
                "turn": number,
                "label": labels[number],
                "pitch_count": total,
                "pitches": [
                    {**pitch, "usage_pct": _rate(pitch["pitch_count"], total)} for pitch in pitches
                ],
            }
        )
    return {
        "performance": performance,
        "pitch_mix": pitch_mix,
        "assigned_pitch_count": sum(row["pitch_count"] for row in performance),
        "total_pitch_count": total_pitches,
    }


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
            Game.season,
            func.count(Pitch.pitch_id).label("pitch_count"),
            func.count(func.distinct(Pitch.game_pk)).label("games"),
            func.min(Game.game_date).label("first_game_date"),
            func.max(Game.game_date).label("last_game_date"),
        )
        .select_from(Player)
        .join(Pitch, Pitch.pitcher_id == Player.mlb_id)
        .join(Game, Game.game_pk == Pitch.game_pk)
        .where(*conditions)
        .group_by(Player.mlb_id, Player.player_name, Player.throws, team, Game.season)
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
                "seasons": [],
                "team_seasons": {},
                "pitch_count": 0,
                "games": 0,
                "first_game_date": row["first_game_date"].isoformat(),
                "last_game_date": row["last_game_date"].isoformat(),
            },
        )
        if row["team"] and row["team"] not in pitcher["teams"]:
            pitcher["teams"].append(row["team"])
        if row["season"] is not None:
            season = int(row["season"])
            if season not in pitcher["seasons"]:
                pitcher["seasons"].append(season)
            if row["team"]:
                seasons = pitcher["team_seasons"].setdefault(row["team"], [])
                if season not in seasons:
                    seasons.append(season)
        pitcher["pitch_count"] += int(row["pitch_count"])
        pitcher["games"] += int(row["games"])
        first_date = row["first_game_date"].isoformat()
        last_date = row["last_game_date"].isoformat()
        pitcher["first_game_date"] = min(pitcher["first_game_date"], first_date)
        pitcher["last_game_date"] = max(pitcher["last_game_date"], last_date)

    for pitcher in pitchers.values():
        pitcher["teams"].sort()
        pitcher["seasons"].sort(reverse=True)
        for seasons in pitcher["team_seasons"].values():
            seasons.sort(reverse=True)
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
    arsenal = _arsenal_rows(conditions, total_pitches, filters.season, player.throws)
    active_spin_by_pitch = published_active_spin(pitcher_id, filters.season)
    for pitch in arsenal:
        # Official full-season measured value: never an inferred per-pitch
        # efficiency or a date/hand/count-filtered estimate.
        pitch["spin_efficiency_pct"] = active_spin_by_pitch.get(pitch["pitch_type"])
        pitch["spin_efficiency_scope"] = "full_season"
        pitch["spin_efficiency_season"] = filters.season

    # Spin axis is circular: 359° and 1° average to 0°, not 180°.
    # Use the same pitcher, season, count, hand, and date filters as the arsenal.
    spin_axis_statement = (
        select(Pitch.pitch_type, Pitch.spin_axis)
        .join(Game, Game.game_pk == Pitch.game_pk)
        .where(
            *conditions,
            Pitch.spin_axis.between(0, 360),
            func.coalesce(Pitch.description, "").notin_(("automatic_ball", "automatic_strike")),
        )
    )
    axis_vectors: dict[str, list[float]] = {}
    for pitch_type, angle in db.session.execute(spin_axis_statement):
        sine, cosine, count = axis_vectors.setdefault(pitch_type, [0.0, 0.0, 0.0])
        direction = radians(float(angle))
        axis_vectors[pitch_type] = [
            sine + sin(direction),
            cosine + cos(direction),
            count + 1,
        ]
    for pitch in arsenal:
        sine, cosine, count = axis_vectors.get(pitch["pitch_type"], (0.0, 0.0, 0.0))
        pitch["spin_axis_pitch_count"] = int(count)
        # Opposing directions have no meaningful single average axis.
        pitch["avg_spin_axis"] = (
            round(degrees(atan2(sine, cosine)) % 360, 1) % 360
            if count and hypot(sine, cosine) / count > 1e-6
            else None
        )
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

    published = published_references(pitcher_id, filters.season)
    active_side = filters.batter_sides[0] if len(filters.batter_sides) == 1 else "ALL"
    split_rows = _platoon_rows(conditions)
    for split in split_rows:
        split.update(published[split["batter_side"]])

    tunneling = build_pitch_tunneling(pitcher_id, filters)
    separation = add_tunneling_to_separation(build_pitch_separation(conditions), tunneling)

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
            **published[active_side],
            "stuff_plus": stuff["overall"],
            "location_plus": stuff["location_plus"],
            "pitching_plus": stuff["pitching_plus"],
        },
        "arsenal": arsenal,
        "pitch_roles": build_pitch_roles(arsenal, filters, player.throws),
        "pitch_separation": separation,
        "pitch_tunneling": tunneling,
        "pitch_transition_matrix": build_pitch_transition_matrix(tunneling),
        "pitch_pair_effectiveness": build_pitch_pair_effectiveness(pitcher_id, filters),
        "platoon_splits": split_rows,
        "times_through_order_splits": _times_through_order_splits(conditions, total_pitches),
    }
