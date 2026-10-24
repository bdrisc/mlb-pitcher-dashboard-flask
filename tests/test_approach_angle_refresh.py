"""Backfill identities, idempotence, missing data and preservation checks."""

from datetime import date

import pandas as pd
import pytest

from app.extensions import db
from app.models import Game, Pitch, Player
from app.services.approach_angle_refresh import _source_records, refresh_approach_angles
from app.services.approach_angles import approach_angles


def source_frame():
    return pd.DataFrame(
        [
            dict(
                game_pk=1,
                at_bat_number=1,
                pitch_number=1,
                pitcher=100,
                game_year=2026,
                vx0=8,
                vy0=-140,
                vz0=-4,
                ax=-10,
                ay=25,
                az=-20,
            ),
            dict(
                game_pk=1,
                at_bat_number=1,
                pitch_number=2,
                pitcher=100,
                game_year=2026,
                vx0=None,
                vy0=None,
                vz0=None,
                ax=None,
                ay=None,
                az=None,
            ),
        ]
    )


def populate(app):
    with app.app_context():
        db.session.add(Player(mlb_id=100, player_name="Test"))
        db.session.add(
            Game(
                game_pk=1, season=2026, game_date=date(2026, 4, 1), home_team="BOS", away_team="NYY"
            )
        )
        db.session.flush()
        db.session.add(
            Pitch(
                pitch_id="1_1_1",
                game_pk=1,
                pitcher_id=100,
                batter_id=100,
                at_bat_number=1,
                pitch_number=1,
                pitch_type="FF",
                balls=0,
                strikes=0,
                velocity=96,
                delta_run_expectancy=0.5,
            )
        )
        db.session.commit()


def test_cache_updates_only_existing_angles_and_repeated_run_skips(app, tmp_path):
    populate(app)
    path = tmp_path / "source.csv"
    source_frame().to_csv(path, index=False)
    with app.app_context():
        result = refresh_approach_angles(source_path=path, workers=1)
        assert result["updated_pitches"] == 1
        assert result["vaa_pitches"] == result["haa_pitches"] == 1
        row = db.session.get(Pitch, "1_1_1")
        assert (row.vaa, row.haa) == pytest.approx(
            approach_angles(vx0=8, vy0=-140, vz0=-4, ax=-10, ay=25, az=-20)
        )
        assert row.velocity == 96 and row.delta_run_expectancy == 0.5
        assert db.session.get(Pitch, "1_1_2") is None
        assert refresh_approach_angles(workers=1)["updated_pitches"] == 0


def test_missing_source_id_preserves_entire_pitcher_season(app, monkeypatch):
    populate(app)
    monkeypatch.setattr(
        "app.services.approach_angle_refresh.fetch_trajectory_values", lambda job: {}
    )
    with app.app_context():
        result = refresh_approach_angles(workers=1)
        assert result["failed"] and result["updated_pitches"] == 0
        assert db.session.get(Pitch, "1_1_1").approach_angle_version is None


def test_missing_tracking_is_null_and_marked_processed(app, monkeypatch):
    populate(app)
    frame = source_frame().iloc[[1]].copy()
    frame["pitch_number"] = 1
    monkeypatch.setattr(
        "app.services.approach_angle_refresh.fetch_trajectory_values",
        lambda job: _source_records(frame),
    )
    with app.app_context():
        result = refresh_approach_angles(workers=1)
        assert result["updated_pitches"] == 1 and result["vaa_pitches"] == 0
        row = db.session.get(Pitch, "1_1_1")
        assert row.vaa is None and row.haa is None and row.approach_angle_version == 1
        assert refresh_approach_angles(workers=1)["updated_pitches"] == 0


def test_bad_source_rejected_before_writes_and_ownership_checked(app, tmp_path):
    populate(app)
    for frame in (
        source_frame().drop(columns="ax"),
        pd.concat([source_frame()] * 2),
        source_frame().assign(pitcher=200),
    ):
        path = tmp_path / "bad.csv"
        frame.to_csv(path, index=False)
        with app.app_context():
            with pytest.raises(ValueError):
                refresh_approach_angles(source_path=path, workers=1)
            assert db.session.get(Pitch, "1_1_1").approach_angle_version is None
