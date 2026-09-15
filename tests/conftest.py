"""Shared Flask application fixture."""

from __future__ import annotations

import pandas as pd
import pytest

from app import create_app
from app.extensions import db


@pytest.fixture
def sample_csv(tmp_path):
    path = tmp_path / "statcast.csv"
    pd.DataFrame(
        [
            {
                "player_name": "Sample, Pitcher",
                "game_date": "2026-04-01",
                "game_year": 2026,
                "pitch_type": "FF",
                "release_speed": 95.0,
                "release_spin_rate": 2400,
                "pfx_x": -0.8,
                "pfx_z": 1.3,
                "stand": "R",
                "p_throws": "R",
                "inning_topbot": "Top",
                "balls": 0,
                "strikes": 0,
                "home_team": "BOS",
                "away_team": "NYY",
            },
            {
                "player_name": "Sample, Pitcher",
                "game_date": "2026-05-01",
                "game_year": 2026,
                "pitch_type": "FF",
                "release_speed": 97.0,
                "release_spin_rate": 2500,
                "pfx_x": -0.9,
                "pfx_z": 1.4,
                "stand": "L",
                "p_throws": "R",
                "inning_topbot": "Top",
                "balls": 0,
                "strikes": 2,
                "home_team": "BOS",
                "away_team": "NYY",
            },
            {
                "player_name": "Sample, Pitcher",
                "game_date": "2025-09-01",
                "game_year": 2025,
                "pitch_type": "SL",
                "release_speed": 86.0,
                "release_spin_rate": 2600,
                "pfx_x": 0.2,
                "pfx_z": 0.3,
                "stand": "R",
                "p_throws": "R",
                "inning_topbot": "Top",
                "balls": 1,
                "strikes": 2,
                "home_team": "BOS",
                "away_team": "NYY",
            },
        ]
    ).to_csv(path, index=False)
    return path


@pytest.fixture
def app(sample_csv, tmp_path):
    database_path = tmp_path / "test.db"
    application = create_app(
        {
            "TESTING": True,
            "APP_ENV": "test",
            "APP_VERSION": "test",
            "PITCH_DATA_PATH": str(sample_csv),
            "SQLALCHEMY_DATABASE_URI": f"sqlite:///{database_path.as_posix()}",
            "SQLALCHEMY_ENGINE_OPTIONS": {},
        }
    )
    with application.app_context():
        db.create_all()
    yield application
    with application.app_context():
        db.session.remove()
        db.drop_all()


@pytest.fixture
def client(app):
    return app.test_client()
