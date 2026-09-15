"""Validation, derived-feature, audit, and idempotent-ingestion tests."""

from __future__ import annotations

from pathlib import Path

import pandas as pd
import pytest
from sqlalchemy import func, select

from app.extensions import db
from app.models import Game, IngestionRun, Pitch, Player
from app.services.statcast_ingestion import clean_statcast

PROJECT_ROOT = Path(__file__).resolve().parents[1]


def statcast_rows() -> pd.DataFrame:
    return pd.DataFrame(
        [
            {
                "game_date": "2026-08-07",
                "game_pk": 824566,
                "game_type": "R",
                "at_bat_number": 8,
                "pitch_number": 1,
                "inning": 1,
                "inning_topbot": "Top",
                "outs_when_up": 0,
                "home_team": "CLE",
                "away_team": "CWS",
                "player_name": "Pitcher, Test",
                "pitcher": 800048,
                "batter": 700001,
                "stand": "R",
                "p_throws": "L",
                "balls": 0,
                "strikes": 0,
                "pitch_type": "FF",
                "pitch_name": "4-Seam Fastball",
                "description": "called_strike",
                "events": None,
                "type": "S",
                "bb_type": None,
                "zone": 5,
                "release_speed": 94.2,
                "effective_speed": 95.0,
                "release_spin_rate": 2380,
                "release_extension": 6.6,
                "release_pos_x": 2.1,
                "release_pos_y": 54.0,
                "release_pos_z": 5.8,
                "pfx_x": 0.7,
                "pfx_z": 1.4,
                "plate_x": 0.1,
                "plate_z": 2.6,
                "sz_top": 3.4,
                "sz_bot": 1.5,
                "arm_angle": 48.0,
                "n_thruorder_pitcher": 1,
                "launch_speed": None,
                "launch_angle": None,
            },
            {
                "game_date": "2026-08-07",
                "game_pk": 824566,
                "game_type": "R",
                "at_bat_number": 8,
                "pitch_number": 2,
                "inning": 1,
                "inning_topbot": "Top",
                "outs_when_up": 0,
                "home_team": "CLE",
                "away_team": "CWS",
                "player_name": "Pitcher, Test",
                "pitcher": 800048,
                "batter": 700001,
                "stand": "R",
                "p_throws": "L",
                "balls": 0,
                "strikes": 1,
                "pitch_type": "SL",
                "pitch_name": "Slider",
                "description": "swinging_strike",
                "events": None,
                "type": "S",
                "bb_type": None,
                "zone": 14,
                "release_speed": 85.1,
                "effective_speed": 84.6,
                "release_spin_rate": 2640,
                "release_extension": 6.3,
                "release_pos_x": 2.0,
                "release_pos_y": 54.2,
                "release_pos_z": 5.7,
                "pfx_x": -0.2,
                "pfx_z": 0.2,
                "plate_x": 1.2,
                "plate_z": 1.1,
                "sz_top": 3.4,
                "sz_bot": 1.5,
                "arm_angle": 48.5,
                "n_thruorder_pitcher": 1,
                "launch_speed": None,
                "launch_angle": None,
            },
            {
                "game_date": "2026-08-07",
                "game_pk": 824566,
                "game_type": "R",
                "at_bat_number": 9,
                "pitch_number": 1,
                "inning": 1,
                "inning_topbot": "Top",
                "outs_when_up": 1,
                "home_team": "CLE",
                "away_team": "CWS",
                "player_name": "Pitcher, Test",
                "pitcher": 800048,
                "batter": 700002,
                "stand": "L",
                "p_throws": "L",
                "balls": 0,
                "strikes": 0,
                "pitch_type": "CH",
                "pitch_name": "Changeup",
                "description": "hit_into_play",
                "events": "single",
                "type": "X",
                "bb_type": "line_drive",
                "zone": 6,
                "release_speed": 86.0,
                "effective_speed": 86.4,
                "release_spin_rate": 1810,
                "release_extension": 6.7,
                "release_pos_x": 2.2,
                "release_pos_y": 53.9,
                "release_pos_z": 5.8,
                "pfx_x": 1.1,
                "pfx_z": 0.7,
                "plate_x": -0.2,
                "plate_z": 2.4,
                "sz_top": 3.5,
                "sz_bot": 1.6,
                "arm_angle": 47.8,
                "n_thruorder_pitcher": 1,
                "launch_speed": 101.0,
                "launch_angle": 17.0,
            },
        ]
    )


def write_statcast_csv(tmp_path, frame: pd.DataFrame | None = None):
    path = tmp_path / "statcast.csv"
    (frame if frame is not None else statcast_rows()).to_csv(path, index=False)
    return path


def test_cleaning_creates_ids_names_and_scouting_flags():
    cleaned = clean_statcast(statcast_rows())

    assert cleaned["pitch_id"].tolist() == [
        "824566_8_1",
        "824566_8_2",
        "824566_9_1",
    ]
    assert cleaned["pitch_name"].tolist() == ["Four-Seam Fastball", "Slider", "Changeup"]
    assert bool(cleaned.iloc[1]["is_whiff"]) is True
    assert bool(cleaned.iloc[1]["is_chase"]) is True
    assert bool(cleaned.iloc[2]["is_hard_hit"]) is True


def test_cli_ingests_relational_records_and_audits_success(app, tmp_path):
    source = write_statcast_csv(tmp_path)
    result = app.test_cli_runner().invoke(args=["statcast", "ingest", str(source)])

    assert result.exit_code == 0, result.output
    assert "Inserted pitches: 3" in result.output
    with app.app_context():
        assert db.session.scalar(select(func.count()).select_from(Pitch)) == 3
        assert db.session.scalar(select(func.count()).select_from(Game)) == 1
        assert db.session.scalar(select(func.count()).select_from(Player)) == 3
        run = db.session.scalar(select(IngestionRun))
        assert run.status == "succeeded"
        assert run.source_rows == 3
        pitch = db.session.get(Pitch, "824566_8_1")
        assert pitch.horizontal_break_inches == pytest.approx(8.4)
        assert pitch.vertical_break_inches == pytest.approx(16.8)


def test_second_ingestion_updates_without_duplicate_pitches(app, tmp_path):
    source = write_statcast_csv(tmp_path)
    runner = app.test_cli_runner()
    first = runner.invoke(args=["statcast", "ingest", str(source)])
    assert first.exit_code == 0, first.output

    changed = statcast_rows()
    changed.loc[0, "release_speed"] = 95.7
    changed.to_csv(source, index=False)
    second = runner.invoke(args=["statcast", "ingest", str(source)])

    assert second.exit_code == 0, second.output
    assert "Inserted pitches: 0" in second.output
    assert "Updated pitches: 3" in second.output
    with app.app_context():
        assert db.session.scalar(select(func.count()).select_from(Pitch)) == 3
        assert db.session.scalar(select(func.count()).select_from(IngestionRun)) == 2
        assert db.session.get(Pitch, "824566_8_1").velocity == 95.7


def test_validation_failure_is_audited_without_partial_pitch_load(app, tmp_path):
    invalid = statcast_rows().drop(columns="balls")
    source = write_statcast_csv(tmp_path, invalid)
    result = app.test_cli_runner().invoke(args=["statcast", "ingest", str(source)])

    assert result.exit_code != 0
    assert "missing required columns: balls" in result.output
    with app.app_context():
        assert db.session.scalar(select(func.count()).select_from(Pitch)) == 0
        run = db.session.scalar(select(IngestionRun))
        assert run.status == "failed"
        assert run.rejected_rows == 3


def test_bundled_sample_can_populate_a_fresh_database(app):
    source = PROJECT_ROOT / "data" / "sample_statcast.csv"
    result = app.test_cli_runner().invoke(args=["statcast", "ingest", str(source)])

    assert result.exit_code == 0, result.output
    assert "Inserted pitches: 6" in result.output
    with app.app_context():
        assert db.session.scalar(select(func.count()).select_from(Pitch)) == 6
        assert db.session.scalar(select(func.count()).select_from(Game)) == 2
        assert db.session.get(Player, 999001).player_name == "Sample Pitcher"
