"""Regression tests for independently computed, filterable run-prevention formulas."""

import pytest

from app.services.run_prevention import SEASON_BASELINES, calculate_run_prevention


def sample(**overrides):
    counts = {
        "outs": 60,
        "pa": 90,
        "strikeouts": 30,
        "walks": 8,
        "hbp": 2,
        "homers": 3,
        "fly_balls": 28,
        "ground_balls": 22,
        "popups": 6,
        "classified_batted_balls": 60,
        "contact_events": 60,
    }
    counts.update(overrides)
    return counts


def test_fip_and_xfip_follow_event_formulas_and_constant():
    values = calculate_run_prevention(sample(), 2026, 0.300)
    constant = SEASON_BASELINES[2026]
    assert values["fip"] == round((13 * 3 + 3 * 10 - 2 * 30) / 20 + 3.081, 2)
    assert values["xfip"] == round(
        (13 * 28 * constant["hr_fb_rate"] + 3 * 10 - 2 * 30) / 20 + 3.081, 2
    )
    assert values["rp_innings"] == 20
    assert values["rp_pa"] == 90
    assert values["rp_outs"] == 60


def test_fip_denominator_uses_outs_as_thirds_and_skips_zero():
    assert calculate_run_prevention(sample(outs=3), 2026, 0.300)["rp_innings"] == 1
    values = calculate_run_prevention(sample(outs=0), 2026, 0.300)
    assert values["fip"] is None
    assert values["xfip"] is None


def test_siera_published_mlb_bp_equation_and_missing_classifications():
    counts = sample()
    values = calculate_run_prevention(counts, 2026, 0.300)
    k_rate = 30 / 90
    bb_rate = 8 / 90
    net = (22 - 28) / 90
    published = (
        6.145
        - 16.986 * k_rate
        + 11.434 * bb_rate
        - 1.858 * net
        + 7.653 * k_rate**2
        - 6.664 * net * abs(net)
        + 10.130 * k_rate * net
        - 5.195 * bb_rate * net
    )
    assert values["siera"] == pytest.approx(round(published, 2))
    assert calculate_run_prevention(sample(classified_batted_balls=59), 2026, 0.3)["siera"] is None


def test_xera_is_season_baseline_conversion_not_false_savant_claim():
    values = calculate_run_prevention(sample(), 2026, 0.316)
    assert values["xera"] == 4.17
    assert "not official Savant" in values["rp_xera_method"]
    assert calculate_run_prevention(sample(), 2026, None)["xera"] is None


def test_non_reference_season_returns_missing_not_fabricated_constants():
    values = calculate_run_prevention(sample(), 2025, 0.300)
    assert values["fip"] is None
    assert values["xfip"] is None
    assert values["siera"] is None
    assert values["xera"] is None


def test_missing_fly_classification_suppresses_xfip():
    values = calculate_run_prevention(sample(classified_batted_balls=59), 2026, 0.3)
    assert values["fip"] is not None
    assert values["xfip"] is None
