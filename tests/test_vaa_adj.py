"""Vertical residuals, plane alignment, frozen training and safe data updates."""

import json
import math

import numpy as np
import pandas as pd
import pytest

from app.extensions import db
from app.models import Pitch
from app.services.vaa_adj import MODEL_PATH, backfill_vaa_adj, front_plate_z, score_vaa_adj
from tests.test_pitcher_profile import profile_client as profile_client_fixture

profile_client = profile_client_fixture

REFERENCE = {
    "model_id": "b" * 64,
    "train_season": 2025,
    "applies_from_season": 2026,
    "groups": {"FF": {"coefficients": [-7.5, 1.0]}},
}


def inputs(**changes):
    return {
        "season": 2026,
        "pitch_type": "FF",
        "plate_z": 2.5,
        "vaa": -4.2,
        "vz0": 0.0,
        "vy0": -130.0,
        "az": 0.0,
        "ay": 25.0,
        **changes,
    }


def test_positive_is_flatter_negative_is_steeper_and_zero_is_real_zero():
    for actual, residual in [(-4.2, 0.8), (-5.6, -0.6), (-5.0, 0.0)]:
        score = score_vaa_adj(**inputs(vaa=actual), reference=REFERENCE)
        assert score["expected_vaa"] == -5.0
        assert score["vaa_adj"] == pytest.approx(residual)
    # No release height or throwing hand is required or adjusted away.
    assert score_vaa_adj(**inputs(), reference=REFERENCE)["vaa_adj"] > 0


def test_front_plate_height_matches_independent_trajectory_solution():
    # Bisection uses position along the flight instead of the scorer's formula.
    vy0, ay, vz0, az, z0 = -130.0, 25.0, 3.0, -20.0, 6.0

    def z_at_y(y):
        lo, hi = 0.0, 0.6
        for _ in range(70):
            t = (lo + hi) / 2
            if 50 + vy0 * t + 0.5 * ay * t * t > y:
                lo = t
            else:
                hi = t
        return z0 + vz0 * t + 0.5 * az * t * t

    front, middle = z_at_y(17 / 12), z_at_y(17 / 24)
    corrected = front_plate_z(season=2026, plate_z=middle, vy0=vy0, ay=ay, vz0=vz0, az=az)
    assert corrected == pytest.approx(front, abs=1e-12)
    assert front > middle
    assert front_plate_z(season=2025, plate_z=front) == front
    assert front_plate_z(season=2026, plate_z=2.5, vy0=-130, ay=0, vz0=0, az=0) == 2.5


@pytest.mark.parametrize(
    "change",
    [
        {"vaa": None},
        {"vaa": math.inf},
        {"plate_z": None},
        {"plate_z": math.nan},
        {"vy0": None},
        {"vy0": 1},
        {"ay": 1000},
        {"vz0": None},
        {"az": None},
        {"pitch_type": "UN"},
        {"season": 2025},
    ],
)
def test_missing_unsupported_and_prior_season_values_are_unavailable(change):
    scored = score_vaa_adj(**inputs(**change), reference=REFERENCE)
    assert scored["vaa_adj"] is None
    assert scored["expected_vaa"] is None


def test_vectorized_trainer_and_runtime_agree():
    from scripts.build_vaa_adj_reference import prepare

    frame = pd.DataFrame(
        [
            {
                "plate_z": 2.5,
                "vz0": 3.0,
                "vy0": -130.0,
                "az": -20.0,
                "ay": 25.0,
                "pitch_type": "FF",
                "game_year": year,
            }
            for year in (2025, 2026)
        ]
    )
    prepared = prepare(frame)
    for _, row in prepared.iterrows():
        location = front_plate_z(
            season=row.game_year, **row[["plate_z", "vz0", "vy0", "az", "ay"]].to_dict()
        )
        assert location == pytest.approx(row.plate_z_front, abs=1e-12)
        score = score_vaa_adj(
            **inputs(
                season=2026,
                plate_z=row.plate_z_front,
                vaa=row.vaa,
                vz0=0,
                az=0,
            ),
            reference=REFERENCE,
        )
        assert score["vaa_adj"] == pytest.approx(row.vaa - (-7.5 + row.plate_z_front))


def test_backfill_preserves_rows_raw_metrics_and_repeats_safely(app, profile_client, monkeypatch):
    monkeypatch.setattr("app.services.vaa_adj.load_reference", lambda: REFERENCE)
    before = profile_client.get("/api/v1/pitchers/100/profile").json
    with app.app_context():
        for key, angle in [("1001_1_1", -4.2), ("1001_1_2", -5.6)]:
            row = db.session.get(Pitch, key)
            row.vaa = angle
            row.plate_z = 2.5
            row.vy0, row.ay, row.vz0, row.az = -130, 25, 0, 0
        db.session.commit()
        result = backfill_vaa_adj(batch_size=1)
        assert result["processed_pitches"] == 4
        assert result["scored_pitches"] == 2
        assert db.session.query(Pitch).count() == 4
        assert backfill_vaa_adj()["processed_pitches"] == 0
        row = db.session.get(Pitch, "1001_1_1")
        assert row.vaa == -4.2 and row.velocity == 95.0
        assert row.vaa_adj == pytest.approx(0.8)
    after = profile_client.get("/api/v1/pitchers/100/profile").json
    for key in (
        "whiff_pct",
        "swstr_pct",
        "run_value_per_100",
        "xwoba_against",
        "k_minus_bb_pct",
        "haaaa",
    ):
        assert after["overall"][key] == before["overall"][key]
    assert after["arsenal"][0]["vaa_adj"] == 0.1
    assert after["arsenal"][0]["vaa_adj_pitch_count"] == 2
    filtered = profile_client.get("/api/v1/pitchers/100/profile?pitch_type=FF&strikes=0").json
    assert filtered["arsenal"][0]["vaa_adj"] == 0.8
    assert filtered["arsenal"][0]["vaa_adj_pitch_count"] == 1
    unsupported = profile_client.get("/api/v1/pitchers/100/profile?pitch_type=SL").json
    assert unsupported["arsenal"][0]["vaa_adj"] is None
    assert unsupported["arsenal"][0]["vaa_adj_pitch_count"] == 0
    html = profile_client.get("/savant-card").get_data(as_text=True)
    assert html.index(">VAA</th>") < html.index(">VAAAdj</th>") < html.index(">HAA</th>")


def test_reference_is_full_prior_season_with_independent_2026_evaluation():
    from app.services.vaa_adj import load_reference

    reference = load_reference()
    assert reference is not None
    assert reference["train_season"] == 2025
    assert reference["applies_from_season"] == 2026
    assert reference["features"] == ["intercept", "plate_z_front"]
    assert reference["plane_y_ft"] == pytest.approx(17 / 12)
    assert all(g["n"] >= 500 and g["pitchers"] >= 5 for g in reference["groups"].values())
    report = json.loads(MODEL_PATH.with_name("vaa_adj_validation_2026.json").read_text())
    assert report["model_id"] == reference["model_id"]
    assert report["validation_season"] == 2026
    assert all(
        report["raw_rows"][y] == c["events"] for y, c in report["verified_source_counts"].items()
    )
    assert report["raw_rows"]["2025"] > 700000 and report["raw_rows"]["2026"] > 700000
    error = sum(g["n"] * g["rmse"] ** 2 for g in report["validation"].values())
    baseline = sum(
        g["n"] * g["unadjusted_baseline"]["rmse"] ** 2 for g in report["validation"].values()
    )
    assert error < baseline
    assert np.isfinite([v for g in reference["groups"].values() for v in g["coefficients"]]).all()


def test_ingestion_scores_new_pitches_and_sparse_import_preserves_scores(
    app, tmp_path, monkeypatch
):
    from app.services.statcast_ingestion import ingest_statcast_file
    from tests.test_statcast_ingestion import statcast_rows

    monkeypatch.setattr("app.services.vaa_adj.load_reference", lambda: REFERENCE)
    frame = statcast_rows()
    trajectory = {"vx0": 3.0, "vy0": -130.0, "vz0": 3.0, "ax": -10.0, "ay": 25.0, "az": -20.0}
    for name, value in trajectory.items():
        frame[name] = value
    path = tmp_path / "vaa.csv"
    frame.to_csv(path, index=False)
    with app.app_context():
        ingest_statcast_file(path)
        row = db.session.get(Pitch, "824566_8_1")
        expected = score_vaa_adj(
            season=2026,
            pitch_type="FF",
            plate_z=row.plate_z,
            vaa=row.vaa,
            **{key: getattr(row, key) for key in ("vz0", "vy0", "az", "ay")},
            reference=REFERENCE,
        )
        assert row.vaa_adj == pytest.approx(expected["vaa_adj"])
        assert row.vaa_adj_model_id == REFERENCE["model_id"]
        score = row.vaa_adj
        frame.drop(columns=list(trajectory)).to_csv(path, index=False)
        ingest_statcast_file(path)
        db.session.expire_all()
        row = db.session.get(Pitch, "824566_8_1")
        assert row.vaa_adj == score
        assert row.vaa_adj_model_id == REFERENCE["model_id"]
