"""Protect source identity, snapshot integrity, and season reference behavior."""

import subprocess
from datetime import date

import pandas as pd
import pytest
from sqlalchemy import select

from app.extensions import db
from app.models import FanGraphsStuff, Game, Pitch, Player
from app.services.fangraphs_fetch import normalize_response
from app.services.fangraphs_stuff import import_grades, profile_grades


def frame(**changes):
    return pd.DataFrame(
        [
            {
                "IDfg": 42,
                "mlb_id": 100,
                "Season": 2026,
                "Stuff+": 114.4,
                "Stf+ FA": 123.2,
                "Stf+ SL": 118,
                **changes,
            }
        ]
    )


def test_import_identity_update_and_null_removal(app):
    with app.app_context():
        assert import_grades(frame(), 2026)["grades"] == 3
        result = profile_grades(100, 2026)
        assert result["overall"] == 114.4
        assert result["pitches"]["FF"] == 123.2
        assert result["pitches"]["ST"] is None
        import_grades(frame(**{"Stuff+": 112, "Stf+ SL": None}), 2026)
        assert profile_grades(100, 2026)["overall"] == 112
        assert profile_grades(100, 2026)["pitches"]["SL"] is None
        assert len(db.session.scalars(select(FanGraphsStuff)).all()) == 2
        assert profile_grades(100, None)["overall"] is None
        assert profile_grades(100, 2025)["overall"] is None


def test_failed_import_preserves_previous_snapshot(app):
    with app.app_context():
        import_grades(frame(), 2026)
        for invalid in (
            frame(Season=2025),
            pd.concat([frame(), frame()]),
            frame(**{"Stuff+": "broken"}),
        ):
            with pytest.raises(ValueError):
                import_grades(invalid, 2026)
            assert profile_grades(100, 2026)["overall"] == 114.4


def test_crosswalk_matches_ids_not_names(app):
    with app.app_context():
        source = frame().drop(columns="mlb_id")
        mapping = pd.DataFrame([{"key_fangraphs": 42, "key_mlbam": 789}])
        import_grades(source, 2026, mapping)
        assert profile_grades(789, 2026)["overall"] == 114.4
        assert profile_grades(100, 2026)["overall"] is None


def test_acquisition_rejects_partial_or_wrong_season():
    row = {
        "playerid": 42,
        "xMLBAMID": 100,
        "Season": 2026,
        "sp_stuff": 114,
        "sp_location": 103,
        "sp_pitching": 108,
        "sp_s_FF": 123,
    }
    result = normalize_response({"data": [row], "totalCount": 1}, 2026)
    assert result.iloc[0]["Stf+ FA"] == 123
    for payload in (
        {"data": [row], "totalCount": 2},
        {"data": [{**row, "Season": 2025}], "totalCount": 1},
    ):
        with pytest.raises(ValueError):
            normalize_response(payload, 2026)


def test_sync_timeout_preserves_grades(app, monkeypatch):
    def timeout(*args, **kwargs):
        raise subprocess.TimeoutExpired("fetch", 1)

    with app.app_context():
        import_grades(frame(), 2026)
    monkeypatch.setattr("app.commands.fangraphs.subprocess.run", timeout)
    result = app.test_cli_runner().invoke(args=["fangraphs", "sync", "--season", "2026"])
    assert result.exit_code != 0
    assert "preserved" in result.output
    with app.app_context():
        assert profile_grades(100, 2026)["overall"] == 114.4


def test_seed_is_idempotent_and_does_not_overwrite_refresh(app):
    runner = app.test_cli_runner()
    assert runner.invoke(args=["fangraphs", "seed-if-needed"]).exit_code == 0
    with app.app_context():
        row = db.session.scalars(select(FanGraphsStuff)).first()
        row.stuff_plus = 222
        key = (row.mlb_id, row.season, row.category)
        db.session.commit()
    assert runner.invoke(args=["fangraphs", "seed-if-needed"]).exit_code == 0
    with app.app_context():
        assert db.session.get(FanGraphsStuff, key).stuff_plus == 222


def test_profile_filters_keep_season_reference_and_withhold_ambiguous_slider(app):
    with app.app_context():
        db.session.add(Player(mlb_id=100, player_name="Test"))
        db.session.add(
            Game(
                game_pk=1, game_date=date(2026, 4, 1), season=2026, home_team="BOS", away_team="NYY"
            )
        )
        for index, pitch_type in enumerate(("FF", "SL", "ST"), 1):
            db.session.add(
                Pitch(
                    pitch_id=str(index),
                    game_pk=1,
                    pitcher_id=100,
                    batter_id=100,
                    at_bat_number=1,
                    pitch_number=index,
                    pitch_type=pitch_type,
                    balls=0,
                    strikes=0,
                    batter_side="R",
                )
            )
        db.session.commit()
        import_grades(frame(), 2026)
    client = app.test_client()
    response = client.get("/api/v1/pitchers/100/profile?season=2026&pitch_type=SL")
    assert response.status_code == 200
    data = response.get_json()
    assert data["overall"]["stuff_plus"] == 114.4
    assert data["arsenal"][0]["stuff_plus"] is None
    assert "withheld" in data["fangraphs"]["message"]
    response = client.get("/api/v1/pitchers/100/profile?season=2026&pitch_type=FF")
    assert response.get_json()["arsenal"][0]["stuff_plus"] == 123.2
    response = client.get("/api/v1/pitchers/100/profile")
    assert response.get_json()["overall"]["stuff_plus"] is None


def test_published_negative_and_zero_grades_are_preserved(app):
    with app.app_context():
        import_grades(frame(**{"Stuff+": -15.96, "Stf+ FA": 0}), 2026)
        result = profile_grades(100, 2026)
        assert result["overall"] == -15.96
        assert result["pitches"]["FF"] == 0


def test_import_all_three_model_grades(app):
    with app.app_context():
        import_grades(
            frame(**{"Location+": 102, "Pitching+": 109, "Loc+ FA": 104, "Pit+ FA": 111}), 2026
        )
        result = profile_grades(100, 2026)
        assert result["location_plus"] == 102
        assert result["pitching_plus"] == 109
        assert result["pitch_location"]["FF"] == 104
        assert result["pitch_pitching"]["FF"] == 111
        assert profile_grades(100, None)["location_plus"] is None


def test_model_metric_order_and_removed_notes(client):
    html = client.get("/savant-card").get_data(as_text=True)
    import re

    metrics = re.findall(r'data-metric="([^"]+)"', html)
    assert metrics[-3:] == ["stuff_plus", "location_plus", "pitching_plus"]
    assert "fangraphs-note" not in html
    assert "Stuff+ source:" not in html
    assert "Full-season reference;" not in html
    assert html.index('scope="col">Stuff+') < html.index('scope="col">Location+')
    assert html.index('scope="col">Location+') < html.index('scope="col">Pitching+')


def test_seed_upgrades_existing_stuff_only_snapshot(app):
    with app.app_context():
        import_grades(frame(mlb_id=605400), 2026)
        assert profile_grades(605400, 2026)["location_plus"] is None
    result = app.test_cli_runner().invoke(args=["fangraphs", "seed-if-needed"])
    assert result.exit_code == 0
    with app.app_context():
        assert profile_grades(605400, 2026)["location_plus"] is not None
        assert profile_grades(605400, 2026)["pitching_plus"] is not None
