"""Directional, same-PA pitch pair outcome rates, coverage and filters."""

from __future__ import annotations

import pytest

from app.extensions import db
from app.models import Pitch
from tests.test_pitcher_profile import PITCHER_ID, _pitch
from tests.test_pitcher_profile import profile_client as profile_client_fixture

profile_client = profile_client_fixture
URL = f"/api/v1/pitchers/{PITCHER_ID}/profile"


@pytest.fixture
def pair_client(app, profile_client):
    with app.app_context():
        db.session.query(Pitch).delete()
        rows = [
            # game_pk, PA, pitch_no, pitch_type, side, balls, strikes,
            # description, event, contact xwOBA estimate, pitcher-opponent RV
            (1001, 1, 1, "FF", "R", 0, 0, "called_strike", None, None, None),
            (1001, 1, 2, "SL", "R", 0, 1, "swinging_strike", None, None, -0.04),
            (1001, 1, 3, "FF", "R", 0, 2, "called_strike", None, None, 0.01),
            (1001, 1, 4, "SL", "R", 1, 2, "foul", None, None, -0.02),
            (1001, 1, 5, "SL", "R", 1, 2, "hit_into_play", "single", 0.7, 0.10),
            (1001, 2, 1, "FF", "L", 0, 0, "called_strike", None, None, None),
            (1001, 2, 2, "SL", "L", 1, 1, "hit_into_play", "single", 0.5, 0.05),
            (1001, 3, 1, "SL", "R", 0, 0, "called_strike", None, None, None),
            (1001, 3, 2, "FF", "R", 0, 1, "foul_tip", None, None, -0.02),
        ]
        for game, pa, number, kind, hand, balls, strikes, desc, event, xwoba, rv in rows:
            db.session.add(
                _pitch(
                    pitch_id=f"pair_{pa}_{number}",
                    game_pk=game,
                    at_bat_number=pa,
                    pitch_number=number,
                    batter_id=200 if hand == "R" else 201,
                    inning_half="Top",
                    batter_side=hand,
                    pitch_type=kind,
                    pitch_name=kind,
                    balls=balls,
                    strikes=strikes,
                    description=desc,
                    events=event,
                    estimated_woba=xwoba,
                    batted_ball_type="line_drive" if desc == "hit_into_play" else None,
                    delta_run_expectancy=rv,
                )
            )
        db.session.commit()
    return profile_client


def _pairs(client, suffix=""):
    response = client.get(URL + suffix)
    assert response.status_code == 200
    return response.json["pitch_pair_effectiveness"]


def test_directional_pair_outcomes_include_exact_second_pitch_denominators(pair_client):
    data = _pairs(pair_client)
    assert data["filter_pitch"] == "second"
    assert data["total_pairs"] == 6
    assert data["small_sample_threshold"] == 30
    pairs = {(p["pitch_a"], p["pitch_b"]): p for p in data["pairs"]}
    assert set(pairs) == {("FF", "SL"), ("SL", "FF"), ("SL", "SL")}

    ff_sl = pairs[("FF", "SL")]
    assert ff_sl["pair_count"] == 3
    assert ff_sl["small_sample"] is True
    assert (ff_sl["whiff_count"], ff_sl["swing_count"], ff_sl["whiff_pct"]) == (1, 3, 33.3)
    assert (ff_sl["csw_count"], ff_sl["csw_pct"]) == (1, 33.3)
    assert (ff_sl["xwoba_batted_balls"], ff_sl["xwoba_scored_batted_balls"]) == (1, 1)
    assert ff_sl["xwoba_on_contact"] == 0.5
    assert ff_sl["rv_scored_pitches"] == 3
    assert ff_sl["run_value_per_100"] == 0.3

    reverse = pairs[("SL", "FF")]
    assert reverse["pair_count"] == 2
    assert (reverse["whiff_count"], reverse["swing_count"], reverse["whiff_pct"]) == (1, 1, 100.0)
    assert reverse["csw_pct"] == 100
    assert reverse["xwoba_on_contact"] is None
    assert reverse["xwoba_batted_balls"] == 0

    repeat = pairs[("SL", "SL")]
    assert repeat["pair_count"] == 1
    assert repeat["xwoba_on_contact"] == 0.7
    assert repeat["run_value_per_100"] == -10.0


def test_second_pitch_filters_preserve_real_previous_pitch(pair_client):
    filtered = _pairs(pair_client, "?pitch_type=SL&batter_side=L")
    assert filtered["total_pairs"] == 1
    assert [(p["pitch_a"], p["pitch_b"]) for p in filtered["pairs"]] == [("FF", "SL")]
    assert filtered["pairs"][0]["xwoba_on_contact"] == 0.5

    counted = _pairs(pair_client, "?pitch_type=SL&balls=1&strikes=1")
    assert counted["total_pairs"] == 1
    assert counted["pairs"][0]["pitch_a"] == "FF"
    assert counted["pairs"][0]["xwoba_on_contact"] == 0.5

    right = _pairs(pair_client, "?batter_side=R&pitch_type=SL")
    assert right["total_pairs"] == 3
    assert right["pairs"][0]["pitch_a"] in ("FF", "SL")


def test_missing_tracking_is_not_treated_as_zero(app, pair_client):
    with app.app_context():
        db.session.get(Pitch, "pair_2_2").estimated_woba = None
        db.session.get(Pitch, "pair_1_4").delta_run_expectancy = None
        db.session.commit()

    rows = {(p["pitch_a"], p["pitch_b"]): p for p in _pairs(pair_client)["pairs"]}
    ff_sl = rows[("FF", "SL")]
    assert ff_sl["xwoba_batted_balls"] == 1
    assert ff_sl["xwoba_scored_batted_balls"] == 0
    assert ff_sl["xwoba_on_contact"] is None
    assert ff_sl["rv_scored_pitches"] == 2
    assert ff_sl["run_value_per_100"] is None
    assert ff_sl["whiff_pct"] == 33.3


def test_pair_contact_xwoba_does_not_use_noncontact_expected_values(app, pair_client):
    # An artificial contact estimate on a strikeout must never inflate or
    # expand xwOBAcon's denominator.
    with app.app_context():
        strikeout = db.session.get(Pitch, "pair_1_2")
        strikeout.events = "strikeout"
        strikeout.estimated_woba = 0.93
        db.session.commit()
    pairs = {(p["pitch_a"], p["pitch_b"]): p for p in _pairs(pair_client)["pairs"]}
    ff_sl = pairs[("FF", "SL")]
    assert ff_sl["pair_count"] == 3
    assert ff_sl["xwoba_batted_balls"] == 1
    assert ff_sl["xwoba_scored_batted_balls"] == 1
    assert ff_sl["xwoba_on_contact"] == 0.5


def test_gaps_and_automatic_calls_cannot_create_new_pairs(app, pair_client):
    with app.app_context():
        db.session.delete(db.session.get(Pitch, "pair_1_3"))
        db.session.get(Pitch, "pair_2_1").description = "automatic_ball"
        db.session.commit()
    data = _pairs(pair_client)
    assert data["total_pairs"] == 3
    assert {(p["pitch_a"], p["pitch_b"]) for p in data["pairs"]} == {
        ("FF", "SL"),
        ("SL", "SL"),
        ("SL", "FF"),
    }


def test_pair_results_never_cross_pa_batter_or_pitcher(app, pair_client):
    with app.app_context():
        db.session.get(Pitch, "pair_1_2").batter_id = 201
        db.session.commit()
    data = _pairs(pair_client)
    assert data["total_pairs"] == 4
    pairs = {(p["pitch_a"], p["pitch_b"]): p for p in data["pairs"]}
    assert pairs[("FF", "SL")]["pair_count"] == 2


def test_empty_pairs_are_reported_without_made_up_rates(pair_client):
    # The filter includes three opening pitches, but no second pitches.
    data = _pairs(pair_client, "?balls=0&strikes=0")
    assert data["total_pairs"] == 0
    assert data["pairs"] == []
    assert data["previous_pitch_types"] == []
