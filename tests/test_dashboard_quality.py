"""Data-driven cross-checks for dashboard directory and denominator corrections."""

from __future__ import annotations

from datetime import date

from app.extensions import db
from app.models import Game
from tests.test_pitcher_profile import PITCHER_ID, _pitch
from tests.test_pitcher_profile import profile_client as profile_client_fixture

profile_client = profile_client_fixture
URL = f"/api/v1/pitchers/{PITCHER_ID}/profile"


def test_directory_lists_only_real_seasons_and_team_seasons(app, profile_client):
    with app.app_context():
        db.session.add(
            Game(
                game_pk=20250001,
                game_date=date(2025, 6, 10),
                season=2025,
                game_type="R",
                home_team="NYY",
                away_team="LAA",
            )
        )
        db.session.add(
            _pitch(
                pitch_id="20250001_1_1",
                game_pk=20250001,
                batter_id=200,
                at_bat_number=1,
                pitch_number=1,
                inning_half="Bot",
                batter_side="R",
                pitch_type="FF",
                description="called_strike",
            )
        )
        db.session.commit()

    response = profile_client.get("/api/v1/pitchers")
    assert response.status_code == 200
    pitchers = response.json["pitchers"]
    assert len(pitchers) == 1
    row = pitchers[0]
    assert row["mlb_id"] == PITCHER_ID
    assert row["teams"] == ["BOS", "LAA"]
    assert row["seasons"] == [2026, 2025]
    assert row["team_seasons"] == {"BOS": [2026], "LAA": [2025]}
    assert row["pitch_count"] == 5

    filtered = profile_client.get("/api/v1/pitchers?team=LAA").json["pitchers"]
    assert len(filtered) == 1
    assert filtered[0]["teams"] == ["LAA"]
    assert filtered[0]["seasons"] == [2025]
    assert filtered[0]["team_seasons"] == {"LAA": [2025]}

    filtered = profile_client.get("/api/v1/pitchers?season=2026").json["pitchers"]
    assert len(filtered) == 1
    assert filtered[0]["teams"] == ["BOS"]
    assert filtered[0]["seasons"] == [2026]


def test_description_variants_count_as_swings_strikes_and_chases(app, profile_client):
    with app.app_context():
        for number, description in enumerate(
            ("hit_into_play_no_out", "hit_into_play_score"), start=20
        ):
            db.session.add(
                _pitch(
                    pitch_id=f"variants_{number}",
                    game_pk=1001,
                    batter_id=200,
                    at_bat_number=number,
                    pitch_number=1,
                    inning_half="Top",
                    batter_side="R",
                    pitch_type="FF",
                    description=description,
                    zone=11,
                    is_in_zone=False,
                    # Old ingests may contain stale stored chase flags.
                    is_chase=False,
                )
            )
        db.session.commit()

    overall = profile_client.get(URL).json["overall"]
    assert overall["physical_pitch_count"] == 6
    assert overall["strike_pct"] == 100.0
    assert overall["swing_pct"] == 83.3
    assert overall["whiff_pct"] == 40.0
    assert overall["csw_pct"] == 50.0
    assert overall["chase_pct"] == 100.0


def test_automatic_calls_do_not_enter_rate_denominators(app, profile_client):
    with app.app_context():
        db.session.add(
            _pitch(
                pitch_id="automatic_called_strike",
                game_pk=1001,
                batter_id=200,
                at_bat_number=41,
                pitch_number=1,
                inning_half="Top",
                pitch_type="FF",
                batter_side="R",
                description="automatic_strike",
                zone=5,
                is_in_zone=True,
                is_strike=True,
                is_csw=True,
            )
        )
        db.session.commit()

    overall = profile_client.get(URL).json["overall"]
    assert overall["physical_pitch_count"] == 4
    assert overall["strike_pct"] == 100.0
    assert overall["csw_pct"] == 75.0
    assert overall["zone_pct"] == 50.0
