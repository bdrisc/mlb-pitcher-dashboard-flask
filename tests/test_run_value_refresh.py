"""Source verification and preservation of the user's existing pitch database."""

from datetime import date

import pandas as pd
import pytest

from app.extensions import db
from app.models import Game, Pitch, Player
from app.services.run_value_refresh import (
    RunValueRefreshError,
    fetch_verified_values,
    refresh_run_values,
    validate_source,
)


def source_frame():
    return pd.DataFrame(
        [
            {
                "game_pk": 1,
                "at_bat_number": 1,
                "pitch_number": 1,
                "delta_run_exp": -0.1,
                "pitch_type": "FF",
                "description": "called_strike",
            },
            {
                "game_pk": 1,
                "at_bat_number": 1,
                "pitch_number": 2,
                "delta_run_exp": 0.3,
                "pitch_type": "FF",
                "description": "foul",
            },
            {
                "game_pk": 1,
                "at_bat_number": 2,
                "pitch_number": 1,
                "delta_run_exp": None,
                "pitch_type": None,
                "description": "ball",
            },
        ]
    )


def test_source_requires_matching_explicit_neutral_total_and_count():
    # Savant includes unclassified source pitch rows in its physical pitch count.
    expected = [{"pitches": 3, "delev_pitcher_run_exp": -0.2}]
    values = validate_source(source_frame(), expected)
    assert values == {"1_1_1": -0.1, "1_1_2": 0.3, "1_2_1": None}
    for invalid in (
        [{"pitches": 2, "delev_pitcher_run_exp": -0.2}],
        [{"pitches": 3, "delev_pitcher_run_exp": -0.5}],
        [{"pitches": 3, "unadj_pitcher_run_exp": -0.2}],
    ):
        with pytest.raises(RunValueRefreshError):
            validate_source(source_frame(), invalid)
    with pytest.raises(RunValueRefreshError):
        validate_source(pd.concat([source_frame(), source_frame()]), expected)


def test_savant_csv_and_neutral_total_both_use_regular_season_only(monkeypatch):
    requests = []

    def fake_download(path, params):
        requests.append((path, params))
        if path == "/statcast_search/csv":
            return source_frame().to_csv(index=False).encode("utf-8")
        return b'[{"pitches": 3, "delev_pitcher_run_exp": -0.2}]'

    monkeypatch.setattr("app.services.run_value_refresh._download", fake_download)
    values = fetch_verified_values((123, 2025, date(2025, 3, 27), date(2025, 9, 28)))

    assert values["1_1_1"] == -0.1
    assert "1_2_1" in values  # Unclassified source row remains identifiable.
    assert len(requests) == 2
    assert {path for path, _ in requests} == {"/statcast_search/csv", "/statcast_search"}
    for _, params in requests:
        assert params["hfGT"] == "R|"
        assert params["hfSea"] == "2025|"


def test_count_mismatch_reports_all_counts_for_safe_diagnosis():
    with pytest.raises(
        RunValueRefreshError,
        match=r"physical=3, CSV rows=3, automatic balls=0, automatic strikes=0, aggregate=2",
    ):
        validate_source(source_frame(), [{"pitches": 2, "delev_pitcher_run_exp": -0.2}])


def test_automatic_balls_and_strikes_excluded_but_real_unclassified_pitches_count():
    frame = source_frame()
    frame.loc[len(frame)] = {
        "game_pk": 1,
        "at_bat_number": 2,
        "pitch_number": 2,
        "delta_run_exp": None,
        "pitch_type": None,
        "description": "automatic_ball",
    }
    frame.loc[len(frame)] = {
        "game_pk": 1,
        "at_bat_number": 2,
        "pitch_number": 3,
        "delta_run_exp": None,
        "pitch_type": None,
        "description": "automatic_strike",
    }
    validated = validate_source(frame, [{"pitches": 3, "delev_pitcher_run_exp": -0.2}])
    assert len(validated) == 5  # Retain non-pitch IDs for local identity matching.
    assert validated["1_2_2"] is None
    assert validated["1_2_3"] is None
    with pytest.raises(
        RunValueRefreshError,
        match=r"automatic balls=1, automatic strikes=1, aggregate=4",
    ):
        validate_source(frame, [{"pitches": 4, "delev_pitcher_run_exp": -0.2}])


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


def test_physical_pitches_with_missing_run_values_count_in_savant_denominator():
    frame = source_frame()
    frame.loc[2, "pitch_type"] = "SI"
    values = validate_source(frame, [{"pitches": 3, "delev_pitcher_run_exp": -0.2}])
    assert values["1_2_1"] is None
    assert len(values) == 3
