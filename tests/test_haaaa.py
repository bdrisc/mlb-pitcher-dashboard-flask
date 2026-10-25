"""Residual identity, temporal reference, plate-plane correction and preservation."""

import math

import pytest

from app.extensions import db
from app.models import Pitch
from app.services.haaaa import backfill_haaaa, front_plate_x, score_haaaa
from tests.test_pitcher_profile import profile_client as profile_client_fixture

profile_client = profile_client_fixture

REFERENCE = {
    "model_id": "a" * 64,
    "train_season": 2025,
    "applies_from_season": 2026,
    "groups": {
        "FF:R": {"coefficients": [-1.0, 0.3, 1.0]},
        "FF:L": {"coefficients": [1.0, 0.3, 1.0]},
    },
}


def inputs(**changes):
    return dict(
        season=2026,
        pitch_type="FF",
        throws="R",
        release_pos_x=-2.0,
        plate_x=-0.5,
        haa=-3.0,
        vx0=0.0,
        vy0=-130.0,
        ax=0.0,
        ay=25.0,
        **changes,
    )


def test_residual_is_signed_observed_minus_expected_and_not_quality_grade():
    example = {**REFERENCE, "groups": {"FF:R": {"coefficients": [-3.0, 0.0, 0.0]}}}
    assert score_haaaa(**{**inputs(), "haa": -1.0}, reference=example)["haaaa"] == 2.0
    values = inputs()
    result = score_haaaa(**values, reference=REFERENCE)
    assert result["expected_haa"] == pytest.approx(-2.1)
    assert result["haaaa"] == pytest.approx(-0.9)
    assert score_haaaa(**{**values, "haa": -1.0}, reference=REFERENCE)["haaaa"] == pytest.approx(
        1.1
    )
    assert score_haaaa(**{**values, "throws": "L"}, reference=REFERENCE)[
        "expected_haa"
    ] == pytest.approx(-0.1)


def test_2026_midpoint_is_converted_to_2025_front_plane():
    vx0, vy0, ax, ay = 5.0, -130.0, -12.0, 25.0

    def at_y(y):
        t = (-math.sqrt(vy0**2 - 2 * ay * (50 - y)) - vy0) / ay
        return -2.0 + vx0 * t + 0.5 * ax * t * t

    front, middle = at_y(17 / 12), at_y(17 / 24)
    corrected = front_plate_x(season=2026, plate_x=middle, vx0=vx0, vy0=vy0, ax=ax, ay=ay)
    assert corrected == pytest.approx(front, abs=1e-12)
    assert front_plate_x(season=2025, plate_x=front) == front
    assert abs(middle - front) > 0.001


@pytest.mark.parametrize(
    "change",
    [
        {"haa": None},
        {"release_pos_x": None},
        {"plate_x": None},
        {"vy0": None},
        {"throws": None},
        {"pitch_type": "UN"},
        {"season": 2025},
        {"haa": float("inf")},
    ],
)
def test_unavailable_context_does_not_become_zero_or_refit(change):
    result = score_haaaa(**{**inputs(), **change}, reference=REFERENCE)
    assert result["haaaa"] is None and result["expected_haa"] is None
    assert result["haaaa_model_id"] == REFERENCE["model_id"]


def test_backfill_and_filtered_api_preserve_existing_fields(app, profile_client, monkeypatch):
    monkeypatch.setattr("app.services.haaaa.load_reference", lambda: REFERENCE)
    with app.app_context():
        row = db.session.get(Pitch, "1001_1_1")
        row.haa = -3.0
        row.vx0 = 0.0
        row.vy0 = -130.0
        row.ax = 0.0
        row.ay = 25.0
        row.release_pos_x = -2.0
        row.plate_x = -0.5
        row2 = db.session.get(Pitch, "1001_1_2")
        row2.haa = -1.0
        row2.vx0 = 0.0
        row2.vy0 = -130.0
        row2.ax = 0.0
        row2.ay = 25.0
        row2.release_pos_x = -2.0
        row2.plate_x = -0.5
        db.session.commit()
        before = db.session.query(Pitch).count()
        report = backfill_haaaa()
        assert report["scored_pitches"] == 2
        db.session.expire_all()
        row = db.session.get(Pitch, "1001_1_1")
        assert row.haa == -3.0 and row.velocity == 95.0
        assert row.haaaa == pytest.approx(-0.9)
        assert db.session.query(Pitch).count() == before
        assert backfill_haaaa()["processed_pitches"] == 0
    data = profile_client.get("/api/v1/pitchers/100/profile?pitch_type=FF").json
    assert data["arsenal"][0]["haaaa"] == 0.1
    assert data["arsenal"][0]["haaaa_pitch_count"] == 2
    filtered = profile_client.get(
        "/api/v1/pitchers/100/profile?pitch_type=FF&balls=0&strikes=0"
    ).json
    assert filtered["arsenal"][0]["haaaa"] == -0.9


def test_frozen_artifact_is_prior_season_complete_and_temporally_evaluated():
    import json

    from app.services.haaaa import MODEL_PATH, load_reference

    reference = load_reference()
    assert reference["train_season"] == 2025
    assert reference["applies_from_season"] == 2026
    assert reference["plane_y_ft"] == pytest.approx(17 / 12)
    assert len(reference["groups"]) == 22
    assert all(
        group["n"] >= 500 and group["pitchers"] >= 5 for group in reference["groups"].values()
    )
    report = json.loads(MODEL_PATH.with_name("haaaa_validation_2026.json").read_text())
    assert report["model_id"] == reference["model_id"]
    assert report["validation_season"] == 2026
    assert report["raw_rows"] == {"2025": 712528, "2026": 716792}
    assert all(
        report["raw_rows"][year] == counts["events"]
        for year, counts in report["verified_source_counts"].items()
    )
    squared_error = sum(row["n"] * row["rmse"] ** 2 for row in report["validation"].values())
    baseline_error = sum(
        row["n"] * row["unadjusted_baseline"]["rmse"] ** 2 for row in report["validation"].values()
    )
    assert squared_error < baseline_error
