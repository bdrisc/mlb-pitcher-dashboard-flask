"""Pitch-pair geometry, matching tracking samples and filtered SQL aggregation."""

from math import hypot

import pytest

from app.extensions import db
from app.models import Pitch
from app.services.pitch_separation import separation_pairs
from tests.test_pitcher_profile import profile_client as profile_client_fixture

profile_client = profile_client_fixture
URL = "/api/v1/pitchers/100/profile"


def centroid(code, velocity, hb, ivb):
    return dict(
        pitch_type=code,
        velocity_mph=velocity,
        horizontal_break_inches=hb,
        induced_vertical_break_inches=ivb,
    )


def test_vector_distance_not_difference_of_movement_magnitudes():
    pair = separation_pairs([centroid("FF", 95, 10, 4), centroid("SL", 85, -10, 4)])[0]
    assert pair["velocity_gap_mph"] == 10
    assert pair["velocity_difference_mph"] == -10
    assert pair["horizontal_difference_inches"] == -20
    assert pair["vertical_difference_inches"] == 0
    assert pair["movement_gap_inches"] == 20
    identical = separation_pairs([centroid("FF", 95, 10, 4), centroid("SI", 95, 10, 4)])[0]
    assert identical["velocity_gap_mph"] == identical["movement_gap_inches"] == 0


def test_unique_pairs_symmetry_and_missing_dimensions():
    pitches = [centroid("FF", 95, 10, 4), centroid("SL", 85, -10, 4), centroid("CH", None, None, 5)]
    pairs = separation_pairs(pitches)
    assert len(pairs) == 3
    reverse = separation_pairs(list(reversed(pitches[:2])))[0]
    assert reverse["movement_gap_inches"] == pairs[0]["movement_gap_inches"]
    assert reverse["horizontal_difference_inches"] == -pairs[0]["horizontal_difference_inches"]
    assert reverse["velocity_difference_mph"] == -pairs[0]["velocity_difference_mph"]
    assert pairs[1]["velocity_gap_mph"] is None
    assert pairs[1]["movement_gap_inches"] is None


def test_api_pairs_use_filtered_unrounded_type_means(profile_client):
    payload = profile_client.get(URL).json
    data = payload["pitch_separation"]
    assert data["reference_pitch_type"] == "FF"
    assert data["difference_convention"] == "pitch_b_minus_pitch_a"
    assert len(data["pairs"]) == 1
    pair = data["pairs"][0]
    assert pair["velocity_gap_mph"] == 10
    assert pair["horizontal_difference_inches"] == 13
    assert pair["vertical_difference_inches"] == -14
    assert pair["movement_gap_inches"] == pytest.approx(hypot(13, 14))
    assert profile_client.get(URL + "?pitch_type=FF").json["pitch_separation"]["pairs"] == []
    assert profile_client.get(URL + "?batter_side=R").json["pitch_separation"]["pairs"] == []
    filtered = profile_client.get(URL + "?balls=0&strikes=0").json["pitch_separation"]["pairs"][0]
    assert filtered["velocity_gap_mph"] == 9
    assert filtered["horizontal_difference_inches"] == 12
    assert filtered["vertical_difference_inches"] == -13


def test_joint_movement_tracking_and_independent_velocity_coverage(app, profile_client):
    with app.app_context():
        db.session.get(Pitch, "1001_1_2").horizontal_break_inches = None
        db.session.get(Pitch, "1002_2_1").vertical_break_inches = None
        db.session.get(Pitch, "1002_3_1").horizontal_break_inches = 8
        db.session.get(Pitch, "1002_2_1").velocity = None
        db.session.get(Pitch, "1002_3_1").velocity = None
        db.session.commit()
    data = profile_client.get(URL).json["pitch_separation"]
    types = {p["pitch_type"]: p for p in data["pitch_types"]}
    assert types["FF"]["horizontal_break_inches"] == -8
    assert types["FF"]["induced_vertical_break_inches"] == 16
    assert types["FF"]["movement_pitch_count"] == 1
    assert types["FF"]["velocity_pitch_count"] == 2
    assert types["SL"]["horizontal_break_inches"] == 8
    assert types["SL"]["induced_vertical_break_inches"] == 2
    assert types["SL"]["movement_pitch_count"] == 1
    assert data["pairs"][0]["movement_gap_inches"] == pytest.approx(hypot(16, 14))
    assert data["pairs"][0]["velocity_gap_mph"] is None


def test_aliases_merge_without_duplicate_pairs_and_nonfinite_values_are_ignored(
    app, profile_client
):
    with app.app_context():
        row = db.session.get(Pitch, "1001_1_2")
        row.pitch_name = "4-Seam Fastball"
        row.velocity = float("inf")
        row.horizontal_break_inches = float("-inf")
        db.session.commit()
    data = profile_client.get(URL).json["pitch_separation"]
    assert len(data["pitch_types"]) == 2 and len(data["pairs"]) == 1
    fastball = next(p for p in data["pitch_types"] if p["pitch_type"] == "FF")
    assert fastball["pitch_count"] == 2
    assert fastball["velocity_mph"] == 95
    assert fastball["velocity_pitch_count"] == fastball["movement_pitch_count"] == 1


def test_no_rounding_before_gap_and_unknown_pitches_do_not_become_fastballs(app, profile_client):
    with app.app_context():
        for row in db.session.query(Pitch):
            row.velocity = 95.04 if row.pitch_type == "FF" else 95.06
            row.horizontal_break_inches = 0.04 if row.pitch_type == "FF" else 0.06
            row.vertical_break_inches = 0
        db.session.commit()
    data = profile_client.get(URL).json["pitch_separation"]
    assert data["pairs"][0]["velocity_gap_mph"] == pytest.approx(0.02)
    assert data["pairs"][0]["movement_gap_inches"] == pytest.approx(0.02)
    with app.app_context():
        for row in db.session.query(Pitch):
            if row.pitch_type == "FF":
                row.pitch_type = "UN"
        db.session.commit()
    data = profile_client.get(URL).json["pitch_separation"]
    assert data["reference_pitch_type"] is None
    assert len(data["pitch_types"]) == 1 and not data["pairs"]
