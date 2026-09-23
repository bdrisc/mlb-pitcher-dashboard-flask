"""Database-backed pitcher profile API tests."""

from __future__ import annotations

from datetime import date

import pytest

from app.extensions import db
from app.models import Game, Pitch, Player

PITCHER_ID = 100


@pytest.fixture
def profile_client(app):
    with app.app_context():
        db.session.add_all(
            [
                Player(mlb_id=PITCHER_ID, player_name="Profile Pitcher", throws="R"),
                Player(mlb_id=200, player_name="Right-Handed Batter", bats="R"),
                Player(mlb_id=201, player_name="Left-Handed Batter", bats="L"),
                Game(
                    game_pk=1001,
                    game_date=date(2026, 4, 1),
                    season=2026,
                    game_type="R",
                    home_team="BOS",
                    away_team="NYY",
                ),
                Game(
                    game_pk=1002,
                    game_date=date(2026, 5, 1),
                    season=2026,
                    game_type="R",
                    home_team="NYY",
                    away_team="BOS",
                ),
            ]
        )
        db.session.add_all(
            [
                _pitch(
                    pitch_id="1001_1_1",
                    game_pk=1001,
                    batter_id=200,
                    at_bat_number=1,
                    pitch_number=1,
                    inning_half="Top",
                    batter_side="R",
                    pitch_type="FF",
                    pitch_name="Four-Seam Fastball",
                    balls=0,
                    strikes=0,
                    zone=5,
                    velocity=95.0,
                    spin_rate=2400,
                    horizontal_break_inches=-8.0,
                    vertical_break_inches=16.0,
                    release_extension=6.2,
                    description="called_strike",
                    is_strike=True,
                    is_swing=False,
                    is_whiff=False,
                    is_csw=True,
                    is_in_zone=True,
                ),
                _pitch(
                    pitch_id="1001_1_2",
                    game_pk=1001,
                    batter_id=200,
                    at_bat_number=1,
                    pitch_number=2,
                    inning_half="Top",
                    batter_side="R",
                    pitch_type="FF",
                    pitch_name="Four-Seam Fastball",
                    balls=0,
                    strikes=1,
                    zone=12,
                    velocity=96.0,
                    spin_rate=2450,
                    horizontal_break_inches=-9.0,
                    vertical_break_inches=17.0,
                    release_extension=6.3,
                    description="swinging_strike",
                    events="strikeout",
                    is_strike=True,
                    is_swing=True,
                    is_whiff=True,
                    is_csw=True,
                    is_in_zone=False,
                    is_chase=True,
                ),
                _pitch(
                    pitch_id="1002_2_1",
                    game_pk=1002,
                    batter_id=201,
                    at_bat_number=2,
                    pitch_number=1,
                    inning_half="Bot",
                    batter_side="L",
                    pitch_type="SL",
                    pitch_name="Slider",
                    balls=0,
                    strikes=0,
                    zone=11,
                    velocity=86.0,
                    spin_rate=2600,
                    horizontal_break_inches=4.0,
                    vertical_break_inches=3.0,
                    release_extension=6.1,
                    description="hit_into_play",
                    batted_ball_type="fly_ball",
                    exit_velocity=100.0,
                    estimated_woba=0.620,
                    events="home_run",
                    is_strike=False,
                    is_swing=True,
                    is_contact=True,
                    is_csw=False,
                    is_in_zone=False,
                    is_chase=True,
                    is_hard_hit=True,
                ),
                _pitch(
                    pitch_id="1002_3_1",
                    game_pk=1002,
                    batter_id=201,
                    at_bat_number=3,
                    pitch_number=1,
                    inning_half="Bot",
                    batter_side="L",
                    pitch_type="SL",
                    pitch_name="Slider",
                    balls=1,
                    strikes=0,
                    zone=6,
                    velocity=85.0,
                    spin_rate=2550,
                    horizontal_break_inches=5.0,
                    vertical_break_inches=2.0,
                    release_extension=6.0,
                    description="foul_tip",
                    exit_velocity=70.0,
                    estimated_woba=0.0,
                    is_strike=True,
                    is_swing=False,
                    is_csw=True,
                    is_in_zone=True,
                ),
            ]
        )
        db.session.commit()
    return app.test_client()


def _pitch(**overrides) -> Pitch:
    values = {
        "pitcher_id": PITCHER_ID,
        "release_pos_x": -1.7,
        "release_pos_z": 5.9,
        "plate_x": 0.1,
        "plate_z": 2.6,
        "strike_zone_top": 3.5,
        "strike_zone_bottom": 1.5,
        "is_strike": False,
        "is_swing": False,
        "is_contact": False,
        "is_whiff": False,
        "is_csw": False,
        "is_in_zone": False,
        "is_chase": False,
        "is_hard_hit": False,
    }
    values.update(overrides)
    return Pitch(**values)


def test_profile_returns_identity_sample_overall_arsenal_and_splits(profile_client):
    response = profile_client.get(f"/api/v1/pitchers/{PITCHER_ID}/profile")

    assert response.status_code == 200
    payload = response.json
    assert payload["pitcher"] == {
        "mlb_id": PITCHER_ID,
        "name": "Profile Pitcher",
        "throws": "R",
        "teams": ["BOS"],
    }
    assert payload["sample"] == {
        "pitches": 4,
        "games": 2,
        "plate_appearances": 2,
        "swings": 3,
        "batted_balls": 1,
        "location_tracked_pitches": 4,
        "out_of_zone_pitches": 2,
        "first_game_date": "2026-04-01",
        "last_game_date": "2026-05-01",
    }
    assert payload["overall"]["avg_velocity"] == 90.5
    assert payload["overall"]["strike_pct"] == 100.0
    assert payload["overall"]["whiff_pct"] == 66.7
    assert payload["overall"]["chase_pct"] == 100.0
    assert payload["overall"]["avg_exit_velocity"] == 100.0
    assert payload["overall"]["hard_hit_pct"] == 100.0
    assert payload["overall"]["xwoba_on_contact"] == 0.62
    assert [pitch["pitch_type"] for pitch in payload["arsenal"]] == ["FF", "SL"]
    assert payload["arsenal"][0]["usage_pct"] == 50.0
    assert [split["label"] for split in payload["platoon_splits"]] == [
        "vs RHH",
        "vs LHH",
    ]


def test_pitcher_directory_returns_ids_and_applies_shared_filters(profile_client):
    response = profile_client.get(
        "/api/v1/pitchers",
        query_string={"pitcher": "profile", "team": "bos", "season": "2026"},
    )

    assert response.status_code == 200
    assert response.json == {
        "query": {"pitcher": "profile", "team": "BOS", "season": 2026},
        "data_freshness": {
            "latest_game_date": "2026-05-01",
            "last_ingested_at": None,
        },
        "pitchers": [
            {
                "mlb_id": PITCHER_ID,
                "name": "Profile Pitcher",
                "throws": "R",
                "teams": ["BOS"],
                "pitch_count": 4,
                "games": 2,
                "first_game_date": "2026-04-01",
                "last_game_date": "2026-05-01",
            }
        ],
    }


def test_profile_applies_shared_filters_before_every_aggregation(profile_client):
    response = profile_client.get(
        f"/api/v1/pitchers/{PITCHER_ID}/profile",
        query_string={
            "team": "bos",
            "pitch_type": "slider",
            "batter_side": "L",
            "season": "2026",
            "date_from": "2026-05-01",
            "home_away": "away",
        },
    )

    assert response.status_code == 200
    payload = response.json
    assert payload["sample"]["pitches"] == 2
    assert payload["sample"]["games"] == 1
    assert payload["query"] == {
        "team": "BOS",
        "pitch_type": ["SL"],
        "batter_side": ["L"],
        "season": 2026,
        "date_from": "2026-05-01",
        "home_away": "away",
    }
    assert len(payload["arsenal"]) == 1
    assert payload["arsenal"][0]["pitch_type"] == "SL"
    assert payload["platoon_splits"][0]["batter_side"] == "L"


def test_profile_rejects_redundant_pitcher_name_filter(profile_client):
    response = profile_client.get(f"/api/v1/pitchers/{PITCHER_ID}/profile?pitcher=Someone%20Else")

    assert response.status_code == 400
    assert response.json["details"] == {"pitcher": ["is not allowed for this endpoint"]}


def test_profile_returns_404_for_unknown_player(profile_client):
    response = profile_client.get("/api/v1/pitchers/999/profile")

    assert response.status_code == 404
    assert response.json == {
        "error": "not_found",
        "message": "Pitcher 999 was not found.",
        "pitcher_id": 999,
    }


def test_profile_returns_404_when_known_player_has_no_matching_pitches(profile_client):
    response = profile_client.get(f"/api/v1/pitchers/{PITCHER_ID}/profile?balls=3")

    assert response.status_code == 404
    assert response.json == {
        "error": "not_found",
        "message": "No pitches matched the supplied pitcher and filters.",
        "pitcher_id": PITCHER_ID,
        "query": {"balls": 3},
    }


def test_chart_data_returns_all_five_filtered_datasets(profile_client):
    response = profile_client.get(f"/api/v1/pitchers/{PITCHER_ID}/charts")

    assert response.status_code == 200
    payload = response.json
    assert payload["pitcher_id"] == PITCHER_ID
    assert payload["sample"] == {"pitches": 4, "scatter_point_limit": 6000}
    assert set(payload["charts"]) == {
        "movement",
        "velocity_trend",
        "release_point",
        "location",
        "usage_by_count",
    }
    assert payload["charts"]["movement"]["available_points"] == 4
    assert payload["charts"]["release_point"]["available_points"] == 4
    assert payload["charts"]["location"]["available_points"] == 4
    assert len(payload["charts"]["velocity_trend"]["rows"]) == 2
    assert len(payload["charts"]["usage_by_count"]["rows"]) == 4
    movement = payload["charts"]["movement"]["points"]
    assert next(point for point in movement if point["pitch_type"] == "FF")["horizontal_break"] > 0
    assert next(point for point in movement if point["pitch_type"] == "SL")["horizontal_break"] < 0


def test_chart_data_uses_the_shared_filter_contract(profile_client):
    response = profile_client.get(
        f"/api/v1/pitchers/{PITCHER_ID}/charts",
        query_string={
            "pitch_type": "slider",
            "batter_side": "left",
            "season": "2026",
            "home_away": "away",
        },
    )

    assert response.status_code == 200
    payload = response.json
    assert payload["query"] == {
        "pitch_type": ["SL"],
        "batter_side": ["L"],
        "season": 2026,
        "home_away": "away",
    }
    assert payload["sample"]["pitches"] == 2
    assert {point["pitch_type"] for point in payload["charts"]["movement"]["points"]} == {"SL"}


def test_chart_data_returns_404_for_an_empty_filtered_sample(profile_client):
    response = profile_client.get(f"/api/v1/pitchers/{PITCHER_ID}/charts?balls=3")

    assert response.status_code == 404
    assert response.json["error"] == "not_found"
    assert response.json["query"] == {"balls": 3}
