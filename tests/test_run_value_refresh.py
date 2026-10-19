"""Source verification and preservation of the user's existing pitch database."""

from datetime import date

import pandas as pd
import pytest

from app.extensions import db
from app.models import Game, Pitch, Player
from app.services.run_value_refresh import (
    RunValueRefreshError,
    refresh_run_values,
    validate_source,
)


def source_frame():
    return pd.DataFrame(
        [
            {"game_pk": 1, "at_bat_number": 1, "pitch_number": 1, "delta_run_exp": -0.1},
            {"game_pk": 1, "at_bat_number": 1, "pitch_number": 2, "delta_run_exp": 0.3},
            {"game_pk": 1, "at_bat_number": 2, "pitch_number": 1, "delta_run_exp": None},
        ]
    )


def test_source_requires_matching_explicit_neutral_total_and_count():
    expected = [{"pitches": 2, "delev_pitcher_run_exp": -0.2}]
    values = validate_source(source_frame(), expected)
    assert values == {"1_1_1": -0.1, "1_1_2": 0.3, "1_2_1": None}
    for invalid in (
        [{"pitches": 3, "delev_pitcher_run_exp": -0.2}],
        [{"pitches": 2, "delev_pitcher_run_exp": -0.5}],
        [{"pitches": 2, "unadj_pitcher_run_exp": -0.2}],
    ):
        with pytest.raises(RunValueRefreshError):
            validate_source(source_frame(), invalid)
    with pytest.raises(RunValueRefreshError):
        validate_source(pd.concat([source_frame(), source_frame()]), expected)


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


def test_refresh_updates_only_run_value_without_inserting_pitches(app, monkeypatch):
    populate(app)
    monkeypatch.setattr(
        "app.services.run_value_refresh.fetch_verified_values",
        lambda job: {"1_1_1": -0.1, "1_1_2": 0.3},
    )
    with app.app_context():
        result = refresh_run_values(pitcher_id=100, season=2026, workers=1)
        assert result["updated_pitches"] == 1
        assert not result["failed"]
        row = db.session.get(Pitch, "1_1_1")
        assert row.delta_run_expectancy == -0.1
        assert row.velocity == 96
        assert db.session.get(Pitch, "1_1_2") is None


def test_missing_pitch_or_unverified_source_preserves_existing_values(app, monkeypatch):
    populate(app)
    monkeypatch.setattr("app.services.run_value_refresh.fetch_verified_values", lambda job: {})
    with app.app_context():
        result = refresh_run_values(pitcher_id=100, workers=1)
        assert result["failed"]
        assert result["updated_pitches"] == 0
        assert db.session.get(Pitch, "1_1_1").delta_run_expectancy == 0.5

    def failed(job):
        raise RunValueRefreshError("Source total did not match")

    monkeypatch.setattr("app.services.run_value_refresh.fetch_verified_values", failed)
    with app.app_context():
        result = refresh_run_values(pitcher_id=100, workers=1)
        assert result["failed"]
        assert db.session.get(Pitch, "1_1_1").delta_run_expectancy == 0.5
