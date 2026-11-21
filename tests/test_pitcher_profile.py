"""Database-backed pitcher profile API tests."""

from __future__ import annotations

from datetime import date

import pytest

from app.extensions import db
from app.models import Game, Pitch, Player, SavantActiveSpin

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


def test_effective_velocity_uses_official_tracked_data_and_active_filters(app, profile_client):
    with app.app_context():
        db.session.get(Pitch, "1001_1_1").effective_velocity = 97.6
        db.session.get(Pitch, "1001_1_2").effective_velocity = 98.2
        db.session.get(Pitch, "1002_2_1").effective_velocity = 85.5
        db.session.get(Pitch, "1002_3_1").effective_velocity = None
        db.session.commit()

    endpoint = f"/api/v1/pitchers/{PITCHER_ID}/profile?season=2026"
    by_type = {pitch["pitch_type"]: pitch for pitch in profile_client.get(endpoint).json["arsenal"]}
    assert by_type["FF"]["avg_effective_velocity"] == 97.9
    assert by_type["FF"]["effective_velocity_pitch_count"] == 2
    assert by_type["SL"]["avg_effective_velocity"] == 85.5
    assert by_type["SL"]["effective_velocity_pitch_count"] == 1
    assert by_type["SL"]["pitch_count"] == 2
    assert by_type["FF"]["avg_velocity"] == 95.5

    ff_one_strike = profile_client.get(endpoint + "&pitch_type=FF&strikes=1").json["arsenal"]
    assert ff_one_strike[0]["avg_effective_velocity"] == 98.2
    assert ff_one_strike[0]["effective_velocity_pitch_count"] == 1

    lefty_batters = profile_client.get(endpoint + "&batter_side=L").json["arsenal"]
    assert lefty_batters[0]["avg_effective_velocity"] == 85.5

    # Automatic calls are not thrown pitches and must be omitted.
    with app.app_context():
        db.session.get(Pitch, "1001_1_1").description = "automatic_ball"
        db.session.commit()
    physical = profile_client.get(endpoint + "&pitch_type=FF").json["arsenal"][0]
    assert physical["avg_effective_velocity"] == 98.2
    assert physical["effective_velocity_pitch_count"] == 1


def test_effective_velocity_missing_tracking_is_unavailable(profile_client):
    rows = profile_client.get(f"/api/v1/pitchers/{PITCHER_ID}/profile").json["arsenal"]
    assert all(pitch["avg_effective_velocity"] is None for pitch in rows)
    assert all(pitch["effective_velocity_pitch_count"] == 0 for pitch in rows)


def test_spin_efficiency_uses_measured_full_season_pitch_type_reference(app, profile_client):
    with app.app_context():
        from datetime import datetime, timezone

        db.session.add_all(
            [
                SavantActiveSpin(
                    mlb_id=PITCHER_ID,
                    season=2026,
                    pitch_type="FF",
                    active_spin_pct=96.2,
                    updated_at=datetime.now(timezone.utc),
                ),
                SavantActiveSpin(
                    mlb_id=PITCHER_ID,
                    season=2026,
                    pitch_type="SL",
                    active_spin_pct=24.5,
                    updated_at=datetime.now(timezone.utc),
                ),
            ]
        )
        db.session.commit()

    endpoint = f"/api/v1/pitchers/{PITCHER_ID}/profile"
    # An explicit season is needed for a meaningful full-season reference.
    no_season = profile_client.get(endpoint).json["arsenal"]
    assert all(pitch["spin_efficiency_pct"] is None for pitch in no_season)

    rows = profile_client.get(endpoint + "?season=2026").json["arsenal"]
    by_type = {pitch["pitch_type"]: pitch for pitch in rows}
    assert by_type["FF"]["spin_efficiency_pct"] == 96.2
    assert by_type["SL"]["spin_efficiency_pct"] == 24.5
    assert by_type["FF"]["spin_efficiency_scope"] == "full_season"
    assert by_type["FF"]["spin_efficiency_season"] == 2026

    # It remains a season-long reference when filtering individual pitches.
    for query in (
        "?season=2026&batter_side=R",
        "?season=2026&strikes=1",
        "?season=2026&date_from=2026-04-01&date_to=2026-04-01",
    ):
        narrowed = profile_client.get(endpoint + query).json["arsenal"]
        assert next(p for p in narrowed if p["pitch_type"] == "FF")["spin_efficiency_pct"] == 96.2

    assert profile_client.get(endpoint + "?season=2025").status_code == 404


def test_release_position_averages_round_to_tenths(app, profile_client):
    with app.app_context():
        for pitch in db.session.query(Pitch):
            pitch.release_pos_z = 5.86
            pitch.release_pos_x = -1.76
        db.session.commit()

    profile = profile_client.get(f"/api/v1/pitchers/{PITCHER_ID}/profile").json
    assert profile["overall"]["avg_release_height"] == 5.9
    assert profile["overall"]["avg_release_side"] == -1.8
    for pitch in profile["arsenal"]:
        assert pitch["avg_release_height"] == 5.9
        assert pitch["avg_release_side"] == -1.8


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


def test_chart_data_returns_all_filtered_datasets(profile_client):
    response = profile_client.get(f"/api/v1/pitchers/{PITCHER_ID}/charts")

    assert response.status_code == 200
    payload = response.json
    assert payload["pitcher_id"] == PITCHER_ID
    assert payload["sample"] == {"pitches": 4, "scatter_point_limit": 6000}
    assert set(payload["charts"]) == {
        "movement",
        "velocity_trend",
        "inning_progression",
        "release_point",
        "location_heatmaps",
        "usage_by_count",
    }
    assert payload["charts"]["movement"]["available_points"] == 4
    assert payload["charts"]["release_point"]["available_points"] == 4
    heatmaps = payload["charts"]["location_heatmaps"]
    assert [p["pitch_type"] for p in heatmaps["pitch_types"]] == ["FF", "SL"]
    assert [p["pitch_count"] for p in heatmaps["pitch_types"]] == [2, 2]
    assert [(p["pitch_type"], p["batter_side"], p["pitch_count"]) for p in heatmaps["panels"]] == [
        ("FF", "R", 2),
        ("FF", "L", 0),
        ("SL", "R", 0),
        ("SL", "L", 2),
    ]
    assert all(panel["density"] is None for panel in heatmaps["panels"])
    assert heatmaps["strike_zone"] == {
        "left": -0.88,
        "right": 0.88,
        "bottom": 1.2,
        "top": 3.8,
    }
    assert len(payload["charts"]["velocity_trend"]["rows"]) == 2
    assert len(payload["charts"]["usage_by_count"]["rows"]) == 4
    assert payload["charts"]["inning_progression"]["rows"] == []
    assert payload["charts"]["inning_progression"]["pitch_types"] == []
    movement = payload["charts"]["movement"]["points"]
    assert next(point for point in movement if point["pitch_type"] == "FF")["horizontal_break"] > 0
    assert next(point for point in movement if point["pitch_type"] == "SL")["horizontal_break"] < 0


def test_location_heatmaps_are_split_by_pitch_type_and_batter_side(app, profile_client):
    with app.app_context():
        for number, (side, height) in enumerate(((0.3, 2.1), (-0.2, 2.8), (0.1, 2.5)), 3):
            db.session.add(
                _pitch(
                    pitch_id=f"1001_1_{number}",
                    game_pk=1001,
                    batter_id=200,
                    at_bat_number=1,
                    pitch_number=number,
                    batter_side="R",
                    pitch_type="FF",
                    pitch_name="Four-Seam Fastball",
                    plate_x=side,
                    plate_z=height,
                    balls=0,
                    strikes=0,
                    description="called_strike",
                )
            )
        db.session.commit()

    url = f"/api/v1/pitchers/{PITCHER_ID}/charts"
    response = profile_client.get(url)
    assert response.status_code == 200
    assert "location" not in response.json["charts"]
    heatmaps = response.json["charts"]["location_heatmaps"]
    assert [p["pitch_type"] for p in heatmaps["pitch_types"]] == ["FF", "SL"]
    assert [p["pitch_count"] for p in heatmaps["pitch_types"]] == [5, 2]
    fastball_right = heatmaps["panels"][0]
    assert fastball_right["pitch_type"] == "FF"
    assert fastball_right["batter_side"] == "R"
    assert fastball_right["pitch_count"] == 5
    assert fastball_right["kde_sample_count"] == 5
    assert len(fastball_right["density"]) == len(heatmaps["grid"]["y"])
    assert len(fastball_right["density"][0]) == len(heatmaps["grid"]["x"])
    assert (
        max(value for row in fastball_right["density"] for value in row if value is not None) == 1.0
    )

    right_only = profile_client.get(url + "?batter_side=R").json["charts"]["location_heatmaps"]
    assert [p["pitch_type"] for p in right_only["pitch_types"]] == ["FF"]
    assert [panel["pitch_count"] for panel in right_only["panels"]] == [5, 0]

    left_only = profile_client.get(url + "?batter_side=L").json["charts"]["location_heatmaps"]
    assert [p["pitch_type"] for p in left_only["pitch_types"]] == ["SL"]
    assert [panel["pitch_count"] for panel in left_only["panels"]] == [0, 2]
    assert all(panel["density"] is None for panel in left_only["panels"])


def test_inning_progression_groups_by_inning_of_pitcher_appearance(app, profile_client):
    with app.app_context():
        for pitch_id, inning in (
            ("1001_1_1", 1),
            ("1001_1_2", 2),
            ("1002_2_1", 5),
            ("1002_3_1", 6),
        ):
            db.session.get(Pitch, pitch_id).inning = inning
        db.session.commit()

    payload = profile_client.get(f"/api/v1/pitchers/{PITCHER_ID}/charts").json
    chart = payload["charts"]["inning_progression"]
    assert chart["inning_definition"] == "pitcher_inning_of_appearance"
    assert chart["horizontal_direction"] == "arm_side_positive"
    assert [entry["pitch_type"] for entry in chart["pitch_types"]] == ["FF", "SL"]
    lookup = {(row["pitch_type"], row["inning_pitched"]): row for row in chart["rows"]}
    assert len(lookup) == 4
    assert lookup["FF", 1]["avg_velocity"] == 95.0
    assert lookup["FF", 2]["avg_velocity"] == 96.0
    assert lookup["FF", 1]["avg_hb"] == 8.0
    assert lookup["FF", 2]["avg_ivb"] == 17.0
    # Relief entry in the 5th game inning starts at appearance inning 1.
    assert lookup["SL", 1]["avg_velocity"] == 86.0
    assert lookup["SL", 2]["avg_velocity"] == 85.0
    assert lookup["SL", 1]["avg_hb"] == -4.0
    assert lookup["SL", 1]["game_count"] == 1
    assert lookup["SL", 1]["velocity_count"] == 1

    # Filtering out the first inning must not rebase the appearance index.
    filtered = profile_client.get(
        f"/api/v1/pitchers/{PITCHER_ID}/charts",
        query_string={"pitch_type": "SL", "balls": 1},
    ).json["charts"]["inning_progression"]
    assert len(filtered["rows"]) == 1
    assert filtered["rows"][0]["inning_pitched"] == 2
    assert filtered["rows"][0]["pitch_count"] == 1


def test_inning_pitch_types_are_ranked_by_filtered_usage(app, profile_client):
    with app.app_context():
        for pitch in db.session.query(Pitch).filter_by(pitcher_id=PITCHER_ID):
            pitch.inning = 1
        db.session.add(
            _pitch(
                pitch_id="1002_4_1",
                game_pk=1002,
                batter_id=201,
                at_bat_number=4,
                pitch_number=1,
                inning=1,
                pitch_type="SL",
                pitch_name="Slider",
                balls=0,
                strikes=0,
                velocity=85.5,
            )
        )
        db.session.commit()

    chart = profile_client.get(f"/api/v1/pitchers/{PITCHER_ID}/charts").json["charts"][
        "inning_progression"
    ]
    assert [entry["pitch_type"] for entry in chart["pitch_types"]] == ["SL", "FF"]
    assert [entry["pitch_count"] for entry in chart["pitch_types"]] == [3, 2]

    filtered = profile_client.get(f"/api/v1/pitchers/{PITCHER_ID}/charts?pitch_type=FF").json[
        "charts"
    ]["inning_progression"]
    assert [entry["pitch_type"] for entry in filtered["pitch_types"]] == ["FF"]


def test_inning_progression_uses_independent_tracked_counts_and_handedness(app, profile_client):
    with app.app_context():
        db.session.get(Player, PITCHER_ID).throws = "L"
        first = db.session.get(Pitch, "1001_1_1")
        second = db.session.get(Pitch, "1001_1_2")
        first.inning = 1
        second.inning = 1
        second.velocity = None
        second.horizontal_break_inches = None
        first.vertical_break_inches = None
        db.session.commit()

    chart = profile_client.get(f"/api/v1/pitchers/{PITCHER_ID}/charts").json["charts"][
        "inning_progression"
    ]
    row = next(entry for entry in chart["rows"] if entry["pitch_type"] == "FF")
    assert row["pitch_count"] == 2
    assert row["game_count"] == 1
    assert row["velocity_count"] == 1
    assert row["avg_velocity"] == 95.0
    assert row["hb_count"] == 1
    assert row["avg_hb"] == -8.0  # LHP: no horizontal sign flip.
    assert row["ivb_count"] == 1
    assert row["avg_ivb"] == 17.0


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


def test_run_value_is_pitcher_friendly_weighted_and_respects_filters(app, profile_client):
    with app.app_context():
        for key, value in {
            "1001_1_1": -0.2,
            "1001_1_2": 0.0,
            "1002_2_1": 0.5,
            "1002_3_1": None,
        }.items():
            db.session.get(Pitch, key).delta_run_expectancy = value
        db.session.add(
            _pitch(
                pitch_id="1001_2_1",
                pitch_name="Four-Seam Fastball",
                game_pk=1001,
                batter_id=200,
                at_bat_number=2,
                pitch_number=1,
                pitch_type="FF",
                balls=2,
                strikes=1,
                batter_side="R",
                delta_run_expectancy=0.0,
            )
        )
        db.session.commit()
    data = profile_client.get("/api/v1/pitchers/100/profile?season=2026").get_json()
    assert data["overall"]["run_value_per_100"] == -6.0
    assert data["overall"]["run_value"] == -0.3
    assert data["overall"]["run_value_pitch_count"] == 4
    assert data["overall"]["run_value_denominator"] == 5
    assert data["overall"]["run_value_coverage_pct"] == 80.0
    arsenal = {p["pitch_type"]: p for p in data["arsenal"]}
    assert arsenal["FF"]["run_value_per_100"] == 6.7
    assert arsenal["SL"]["run_value_per_100"] == -25.0
    assert (
        data["overall"]["run_value_per_100"]
        != (arsenal["FF"]["run_value_per_100"] + arsenal["SL"]["run_value_per_100"]) / 2
    )
    filtered = profile_client.get(
        "/api/v1/pitchers/100/profile?season=2026&batter_side=R&date_to=2026-04-30"
    ).get_json()
    assert filtered["overall"]["run_value_per_100"] == 6.7
    assert filtered["overall"]["run_value_coverage_pct"] == 100.0
    zero = profile_client.get(
        "/api/v1/pitchers/100/profile?season=2026&balls=0&strikes=1"
    ).get_json()
    assert zero["overall"]["run_value_per_100"] == 0.0


def test_run_value_missing_stays_missing(profile_client):
    data = profile_client.get("/api/v1/pitchers/100/profile?season=2026").get_json()
    assert data["overall"]["run_value_per_100"] is None
    assert data["overall"]["run_value_pitch_count"] == 0
    assert all(p["run_value_per_100"] is None for p in data["arsenal"])


def test_run_value_matches_savant_published_2026_nola_arsenal(app):
    import csv
    from pathlib import Path

    path = Path(__file__).parent / "fixtures" / "savant_nola_2026_rv.csv"
    with path.open() as source:
        source_rows = list(csv.DictReader(source))
    with app.app_context():
        db.session.add(Player(mlb_id=605400, player_name="Aaron Nola"))
        db.session.add(
            Game(
                game_pk=1, game_date=date(2026, 9, 26), season=2026, home_team="PHI", away_team="TB"
            )
        )
        db.session.flush()
        rows = []
        for index, row in enumerate(source_rows):
            rows.append(
                dict(
                    pitch_id=str(index),
                    game_pk=1,
                    pitcher_id=605400,
                    batter_id=605400,
                    at_bat_number=index + 1,
                    pitch_number=1,
                    pitch_type=row["pitch_type"] or "UN",
                    balls=0,
                    strikes=0,
                    delta_run_expectancy=(
                        float(row["delta_run_exp"]) if row["delta_run_exp"] else None
                    ),
                )
            )
        db.session.execute(Pitch.__table__.insert(), rows)
        db.session.commit()
    data = app.test_client().get("/api/v1/pitchers/605400/profile?season=2026").get_json()
    assert data["overall"]["run_value_pitch_count"] == 2946
    assert data["overall"]["run_value"] == -22.272
    assert data["overall"]["run_value_per_100"] == -0.8
    expected = {"FF": -2.1, "SI": -2.8, "KC": 1.1, "CH": 1.0, "FC": -3.2, "SL": -3.8}
    for pitch in data["arsenal"]:
        if pitch["pitch_type"] in expected:
            assert pitch["run_value_per_100"] == expected[pitch["pitch_type"]]


def test_xwoba_against_includes_terminal_outcomes_and_respects_filters(app, profile_client):
    with app.app_context():
        # One strikeout and one batted ball: contact-only stays .620, while
        # overall includes the strikeout's zero weight and becomes .310.
        db.session.get(Pitch, "1001_1_2").estimated_woba = 0.0
        db.session.commit()
    data = profile_client.get(f"/api/v1/pitchers/{PITCHER_ID}/profile").json
    assert data["overall"]["xwoba_against"] == 0.310
    assert data["overall"]["xwoba_on_contact"] == 0.620
    filtered = profile_client.get(f"/api/v1/pitchers/{PITCHER_ID}/profile?batter_side=R").json
    assert filtered["overall"]["xwoba_against"] == 0.0

    outcomes = [
        ("walk", 0.698223),
        ("hit_by_pitch", 0.729169),
        ("sac_fly", 0.120),
        ("intent_walk", 0.9),
        ("sac_bunt", 0.9),
        ("sac_bunt_double_play", 0.9),
        ("catcher_interf", 0.9),
        ("truncated_pa", 0.9),
        ("field_out", None),
        (None, 0.9),
    ]
    with app.app_context():
        for i, (event, weight) in enumerate(outcomes, start=10):
            db.session.add(
                _pitch(
                    pitch_id=f"1001_{i}_1",
                    game_pk=1001,
                    batter_id=200,
                    at_bat_number=i,
                    pitch_number=1,
                    inning_half="Top",
                    batter_side="R",
                    pitch_type="FF",
                    pitch_name="Four-Seam Fastball",
                    events=event,
                    balls=0,
                    strikes=0,
                    estimated_woba=weight,
                )
            )
        db.session.commit()
    data = profile_client.get(f"/api/v1/pitchers/{PITCHER_ID}/profile").json
    assert data["overall"]["xwoba_against"] == round((0.620 + 0.698223 + 0.729169 + 0.120) / 5, 3)


def test_xwoba_against_unavailable_is_not_zero(app, profile_client):
    with app.app_context():
        for pitch in db.session.query(Pitch):
            pitch.estimated_woba = None
        db.session.commit()
    data = profile_client.get(f"/api/v1/pitchers/{PITCHER_ID}/profile").json
    assert data["overall"]["xwoba_against"] is None


def test_k_minus_bb_uses_raw_counts_including_intentional_walks(app, profile_client):
    url = f"/api/v1/pitchers/{PITCHER_ID}/profile"
    assert profile_client.get(url).json["overall"]["k_minus_bb_pct"] == 50.0
    with app.app_context():
        db.session.get(Pitch, "1001_1_1").events = "walk"
        db.session.get(Pitch, "1002_2_1").events = None
        db.session.get(Pitch, "1002_3_1").events = "intent_walk"
        db.session.commit()
    assert profile_client.get(url).json["overall"]["k_minus_bb_pct"] == -33.3
    assert profile_client.get(url + "?batter_side=R").json["overall"]["k_minus_bb_pct"] == 0.0
    assert profile_client.get(url + "?batter_side=L").json["overall"]["k_minus_bb_pct"] == -100.0
    with app.app_context():
        for pitch in db.session.query(Pitch):
            pitch.events = None
        db.session.commit()
    assert profile_client.get(url).json["overall"]["k_minus_bb_pct"] is None


def test_approach_angles_average_individual_fits_and_follow_filters(app, profile_client):
    with app.app_context():
        db.session.get(Pitch, "1001_1_1").vaa = -4.0
        db.session.get(Pitch, "1001_1_1").haa = 2.0
        db.session.get(Pitch, "1001_1_2").vaa = -6.0
        db.session.get(Pitch, "1001_1_2").haa = -1.0
        db.session.get(Pitch, "1002_2_1").vaa = -9.0
        db.session.commit()
    url = f"/api/v1/pitchers/{PITCHER_ID}/profile"
    arsenal = {p["pitch_type"]: p for p in profile_client.get(url).json["arsenal"]}
    assert arsenal["FF"]["vaa"] == -5.0
    assert arsenal["FF"]["haa"] == 0.5
    assert arsenal["FF"]["vaa_pitch_count"] == 2
    assert arsenal["SL"]["vaa"] == -9.0
    assert arsenal["SL"]["vaa_pitch_count"] == 1
    assert arsenal["SL"]["haa"] is None
    assert arsenal["SL"]["haa_pitch_count"] == 0
    filtered = profile_client.get(url + "?balls=0&strikes=0&pitch_type=FF").json
    assert filtered["arsenal"][0]["vaa"] == -4.0


def test_swstr_uses_pooled_physical_pitch_counts_and_shared_filters(app, profile_client):
    # Unequal pitch-type samples ensure the overall rate cannot be an average
    # of the per-type rates. Stored whiff flags deliberately remain false.
    with app.app_context():
        db.session.query(Pitch).delete()
        descriptions = {
            "FF": [
                "swinging_strike",
                "SWINGING_STRIKE_BLOCKED",
                "foul_tip",
                "missed_bunt",
                "foul_bunt",
                "bunt_foul_tip",
                "ball",
                None,
            ],
            "SL": ["swinging_strike", "hit_into_play", "automatic_ball", "automatic_strike"],
        }
        for code, outcomes in descriptions.items():
            for number, description in enumerate(outcomes, 1):
                db.session.add(
                    _pitch(
                        pitch_id=f"swstr_{code}_{number}",
                        batter_id=200,
                        balls=0,
                        strikes=0,
                        game_pk=1001 if code == "FF" else 1002,
                        pitch_type=code,
                        pitch_name=code,
                        batter_side="R" if code == "FF" else "L",
                        at_bat_number=number,
                        pitch_number=1,
                        description=description,
                    )
                )
        db.session.commit()
    payload = profile_client.get(f"/api/v1/pitchers/{PITCHER_ID}/profile").json
    overall = payload["overall"]
    assert (overall["swinging_strike_count"], overall["swstr_pitch_count"]) == (3, 10)
    assert overall["swstr_pct"] == 30.0
    arsenal = {pitch["pitch_type"]: pitch for pitch in payload["arsenal"]}
    assert arsenal["FF"]["swstr_pct"] == 25.0
    assert arsenal["SL"]["swstr_pct"] == 50.0
    for query, rate, denominator in [
        ({"pitch_type": "FF"}, 25.0, 8),
        ({"batter_side": "L"}, 50.0, 2),
        ({"date_from": "2026-05-01"}, 50.0, 2),
    ]:
        filtered = profile_client.get(
            f"/api/v1/pitchers/{PITCHER_ID}/profile", query_string=query
        ).json
        assert filtered["overall"]["swstr_pct"] == rate
        assert filtered["overall"]["swstr_pitch_count"] == denominator
        assert filtered["arsenal"][0]["swstr_pct"] == rate


@pytest.mark.parametrize(
    "description,expected",
    [
        ("swinging_strike", 100.0),
        ("swinging_strike_blocked", 100.0),
        ("foul_tip", 0.0),
        ("missed_bunt", 0.0),
        ("foul_bunt", 0.0),
        ("bunt_foul_tip", 0.0),
        ("called_strike", 0.0),
        (None, 0.0),
        ("automatic_ball", None),
        ("automatic_strike", None),
    ],
)
def test_swstr_event_classification_and_zero_denominator(
    app, profile_client, description, expected
):
    with app.app_context():
        db.session.query(Pitch).delete()
        db.session.add(
            _pitch(
                pitch_id="swstr_only",
                batter_id=200,
                balls=0,
                strikes=0,
                game_pk=1001,
                pitch_type="UN",
                pitch_name="Unknown",
                description=description,
                at_bat_number=1,
                pitch_number=1,
            )
        )
        db.session.commit()
    payload = profile_client.get(f"/api/v1/pitchers/{PITCHER_ID}/profile").json
    assert payload["overall"]["swstr_pct"] == expected
    assert payload["arsenal"][0]["swstr_pct"] == expected
    assert payload["overall"]["swstr_pitch_count"] == (0 if expected is None else 1)


def test_swstr_display_keeps_fangraphs_metrics_last(profile_client):
    html = profile_client.get("/savant-card").get_data(as_text=True)
    assert 'data-metric="swstr_pct"' in html
    assert "SwStr%</th>" in html
    assert html.index('data-metric="whiff_pct"') < html.index('data-metric="swstr_pct"')
    assert html.index('data-metric="swstr_pct"') < html.index('data-metric="stuff_plus"')
    assert html.index('data-metric="stuff_plus"') < html.index('data-metric="location_plus"')
    assert html.index('data-metric="location_plus"') < html.index('data-metric="pitching_plus"')


def test_xba_uses_savant_scored_at_bat_denominator(app, profile_client):
    with app.app_context():
        db.session.get(Pitch, "1002_2_1").estimated_ba = 0.8
        cases = [
            ("field_out", 0.2),
            ("force_out", None),
            ("walk", 0.99),
            ("intent_walk", 0.99),
            ("hit_by_pitch", 0.99),
            ("sac_fly", 0.99),
            ("sac_fly_double_play", 0.99),
            ("sac_bunt", 0.99),
            ("sac_bunt_double_play", 0.99),
            ("catcher_interf", 0.99),
            ("truncated_pa", 0.99),
            (None, 0.99),
        ]
        for i, (event, estimate) in enumerate(cases, start=10):
            db.session.add(
                _pitch(
                    pitch_id=f"1001_{i}_1",
                    game_pk=1001,
                    batter_id=200,
                    at_bat_number=i,
                    pitch_number=1,
                    inning_half="Top",
                    batter_side="R",
                    pitch_type="FF",
                    pitch_name="Four-Seam Fastball",
                    balls=0,
                    strikes=0,
                    description="hit_into_play" if event else "foul",
                    events=event,
                    estimated_ba=estimate,
                )
            )
        db.session.commit()

    url = f"/api/v1/pitchers/{PITCHER_ID}/profile"
    data = profile_client.get(url).json
    assert data["overall"]["xba"] == 0.333
    assert data["overall"]["xba_at_bats"] == 4
    assert data["overall"]["xba_scored_at_bats"] == 3
    assert data["overall"]["xba_untracked_at_bats"] == 1
    arsenal = {row["pitch_type"]: row for row in data["arsenal"]}
    assert arsenal["FF"]["xba"] == 0.1
    assert arsenal["SL"]["xba"] == 0.8
    splits = {row["batter_side"]: row for row in data["platoon_splits"]}
    assert splits["R"]["xba"] == 0.1
    assert splits["L"]["xba"] == 0.8
    assert profile_client.get(url + "?pitch_type=SL").json["overall"]["xba"] == 0.8
    assert profile_client.get(url + "?batter_side=R").json["overall"]["xba"] == 0.1


def test_xba_strikeouts_zero_and_untracked_at_bats_not_zero(app, profile_client):
    url = f"/api/v1/pitchers/{PITCHER_ID}/profile?pitch_type=FF"
    assert profile_client.get(url).json["overall"]["xba"] == 0.0
    with app.app_context():
        db.session.get(Pitch, "1001_1_2").events = "field_out"
        db.session.commit()
    missing = profile_client.get(url).json["overall"]
    assert missing["xba"] is None
    assert missing["xba_at_bats"] == 1
    assert missing["xba_scored_at_bats"] == 0
    with app.app_context():
        record = db.session.get(Pitch, "1001_1_2")
        record.events = "strikeout_double_play"
        record.estimated_ba = 0.75
        db.session.commit()
    restored = profile_client.get(url).json["overall"]
    assert restored["xba"] == 0.0
    assert restored["xba_scored_at_bats"] == 1


def test_xba_visible_in_overall_results(profile_client):
    html = profile_client.get("/savant-card").get_data(as_text=True)
    assert 'data-metric="xba"' in html
    assert html.index('data-metric="xwoba_against"') < html.index('data-metric="xba"')


def test_xslg_matches_savant_expected_total_bases_per_scored_at_bat(app, profile_client):
    with app.app_context():
        db.session.get(Pitch, "1002_2_1").estimated_slg = 1.2
        db.session.get(Pitch, "1001_1_2").estimated_slg = 3.5
        for index, (event, estimate) in enumerate(
            [
                ("field_out", 0.4),
                ("force_out", None),
                ("walk", 4.0),
                ("hit_by_pitch", 4.0),
                ("sac_fly", 4.0),
                ("intent_walk", 4.0),
                (None, 2.0),
            ],
            start=10,
        ):
            db.session.add(
                _pitch(
                    pitch_id=f"1001_{index}_1",
                    game_pk=1001,
                    batter_id=200,
                    at_bat_number=index,
                    pitch_number=1,
                    inning_half="Top",
                    batter_side="R",
                    pitch_type="FF",
                    pitch_name="Four-Seam Fastball",
                    balls=0,
                    strikes=0,
                    description="hit_into_play",
                    events=event,
                    estimated_slg=estimate,
                )
            )
        db.session.commit()
    url = f"/api/v1/pitchers/{PITCHER_ID}/profile"
    all_pitches = profile_client.get(url).json
    assert all_pitches["overall"]["xslg"] == 0.533
    assert all_pitches["overall"]["xslg_at_bats"] == 4
    assert all_pitches["overall"]["xslg_scored_at_bats"] == 3
    assert all_pitches["overall"]["xslg_untracked_at_bats"] == 1
    pitches = {pitch["pitch_type"]: pitch for pitch in all_pitches["arsenal"]}
    assert pitches["FF"]["xslg"] == 0.2
    assert pitches["SL"]["xslg"] == 1.2
    sides = {side["batter_side"]: side for side in all_pitches["platoon_splits"]}
    assert sides["R"]["xslg"] == 0.2
    assert sides["L"]["xslg"] == 1.2
    assert profile_client.get(url + "?pitch_type=SL").json["overall"]["xslg"] == 1.2
    assert profile_client.get(url + "?batter_side=R").json["overall"]["xslg"] == 0.2


def test_xslg_returns_missing_until_contact_is_scored_but_allows_k_only(app, profile_client):
    url = f"/api/v1/pitchers/{PITCHER_ID}/profile"
    untracked = profile_client.get(url).json["overall"]
    assert untracked["xslg"] is None
    strikeouts_only = profile_client.get(url + "?pitch_type=FF").json["overall"]
    assert strikeouts_only["xslg"] == 0.0
    with app.app_context():
        db.session.get(Pitch, "1002_2_1").estimated_slg = 0.9
        db.session.commit()
    scored = profile_client.get(url).json["overall"]
    assert scored["xslg"] == 0.45


def test_xslg_display_appears_with_xba(profile_client):
    html = profile_client.get("/savant-card").get_data(as_text=True)
    assert 'data-metric="xslg"' in html
    assert html.index('data-metric="xba"') < html.index('data-metric="xslg"')


def test_published_season_rates_replace_computed_metrics(app, profile_client):
    import pandas as pd
    from sqlalchemy import func, select

    from app.models import PublishedPitchingMetric
    from app.services.published_pitching import (
        import_fangraphs_published,
        import_savant_xera,
    )

    url = f"/api/v1/pitchers/{PITCHER_ID}/profile?season=2026"
    empty = profile_client.get(url).json["overall"]
    assert all(empty[name] is None for name in ("fip", "xfip", "siera", "xera"))

    with app.app_context():
        before = db.session.scalar(select(func.count()).select_from(Pitch))
        for split, fip, xfip, siera in (
            ("ALL", 3.45, 3.22, 3.11),
            ("R", 3.01, 2.77, 2.82),
            ("L", 4.12, 4.01, 3.89),
        ):
            source = pd.DataFrame(
                [
                    {
                        "mlb_id": PITCHER_ID,
                        "IDfg": 456,
                        "Season": 2026,
                        "FIP": fip,
                        "xFIP": xfip,
                        "SIERA": siera,
                    }
                ]
            )
            import_fangraphs_published(source, 2026, split)
        import_savant_xera(
            pd.DataFrame([{"player_id": PITCHER_ID, "year": 2026, "xera": 2.95}]),
            2026,
        )
        assert db.session.scalar(select(func.count()).select_from(Pitch)) == before
        assert db.session.scalar(select(func.count()).select_from(PublishedPitchingMetric)) == 3

    result = profile_client.get(url).json
    assert result["overall"]["fip"] == 3.45
    assert result["overall"]["xfip"] == 3.22
    assert result["overall"]["siera"] == 3.11
    assert result["overall"]["xera"] == 2.95
    assert result["overall"]["reference_scope"] == "full_season"

    right = profile_client.get(url + "&batter_side=R").json["overall"]
    left = profile_client.get(url + "&batter_side=L").json["overall"]
    assert right["fip"] == 3.01
    assert right["xfip"] == 2.77
    assert right["siera"] == 2.82
    assert left["fip"] == 4.12
    assert right["xera"] is None
    assert left["xera"] is None

    for extra in ("&pitch_type=FF", "&date_from=2026-04-01", "&balls=0&strikes=1"):
        assert profile_client.get(url + extra).json["overall"]["fip"] == 3.45

    sides = {row["batter_side"]: row for row in result["platoon_splits"]}
    assert sides["R"]["fip"] == 3.01
    assert sides["L"]["siera"] == 3.89
    assert sides["L"]["xera"] is None
    arsenal = result["arsenal"]
    assert all("fip" not in row and "xera" not in row for row in arsenal)

    assert (
        profile_client.get(f"/api/v1/pitchers/{PITCHER_ID}/profile").json["overall"]["fip"] is None
    )
    assert profile_client.get(url.replace("2026", "2025")).status_code == 404


def test_published_run_prevention_labels_show_sources_not_estimates(profile_client):
    html = profile_client.get("/savant-card").get_data(as_text=True)
    for key in ("fip", "xfip", "siera", "xera"):
        assert f'data-metric="{key}"' in html
    assert "Published" in html
    assert "FanGraphs" in html
    assert "Baseball Savant" in html
    assert "Unadjusted" not in html
    assert "xERA*" not in html


def test_batted_ball_mix_uses_one_decimal_largest_remainder():
    from app.services.pitcher_profiles import _batted_ball_percentages

    assert _batted_ball_percentages((0, 0, 0, 0)) == (None, None, None, None)
    assert _batted_ball_percentages((0, 1, 0, 0)) == (0.0, 100.0, 0.0, 0.0)
    assert _batted_ball_percentages((1, 1, 1, 0)) == (33.4, 33.3, 33.3, 0.0)
    assert _batted_ball_percentages((1, 1, 1, 1)) == (25.0, 25.0, 25.0, 25.0)
    for counts in ((1, 3, 7, 2), (10, 11, 9, 8), (999, 123, 1, 2)):
        assert round(sum(_batted_ball_percentages(counts)), 1) == 100.0


def test_batted_ball_mix_updates_for_pitch_and_handedness_filters(profile_client):
    url = f"/api/v1/pitchers/{PITCHER_ID}/profile?season=2026"
    profile = profile_client.get(url).json
    overall = profile["overall"]
    assert (overall["gb_pct"], overall["fb_pct"], overall["ld_pct"], overall["pu_pct"]) == (
        0.0,
        100.0,
        0.0,
        0.0,
    )
    assert overall["batted_ball_type_count"] == 1
    assert overall["batted_ball_type_unclassified"] == 0

    by_side = {s["batter_side"]: s for s in profile["platoon_splits"]}
    assert by_side["L"]["fb_pct"] == 100.0
    assert all(by_side["R"][key] is None for key in ("gb_pct", "fb_pct", "ld_pct", "pu_pct"))
    assert all(
        profile_client.get(url + "&pitch_type=FF").json["overall"][key] is None
        for key in ("gb_pct", "fb_pct", "ld_pct", "pu_pct")
    )
    assert profile_client.get(url + "&pitch_type=SL").json["overall"]["fb_pct"] == 100.0
    assert profile["arsenal"][0]["batted_ball_type_count"] == 0
    assert profile["arsenal"][1]["fb_pct"] == 100.0


def test_batted_ball_mix_excludes_missing_types_and_keeps_exact_total(app, profile_client):
    with app.app_context():
        for number, kind in enumerate(("ground_ball", "line_drive", "popup", None), start=10):
            db.session.add(
                _pitch(
                    pitch_id=f"1002_{number}_1",
                    game_pk=1002,
                    batter_id=201,
                    at_bat_number=number,
                    pitch_number=1,
                    inning_half="Bot",
                    batter_side="L",
                    pitch_type="SL",
                    pitch_name="Slider",
                    balls=0,
                    strikes=0,
                    description="hit_into_play",
                    batted_ball_type=kind,
                    events="field_out",
                )
            )
        db.session.commit()

    profile = profile_client.get(f"/api/v1/pitchers/{PITCHER_ID}/profile?season=2026").json
    slider = next(row for row in profile["arsenal"] if row["pitch_type"] == "SL")
    for metrics in (
        profile["overall"],
        slider,
        next(row for row in profile["platoon_splits"] if row["batter_side"] == "L"),
    ):
        assert [metrics[key] for key in ("gb_pct", "fb_pct", "ld_pct", "pu_pct")] == [
            25.0,
            25.0,
            25.0,
            25.0,
        ]
        assert metrics["batted_ball_type_count"] == 4
        assert metrics["batted_ball_type_unclassified"] == 1
        assert [metrics[key] for key in ("gb_count", "fb_count", "ld_count", "pu_count")] == [
            1,
            1,
            1,
            1,
        ]

    only_fastballs = profile_client.get(
        f"/api/v1/pitchers/{PITCHER_ID}/profile?season=2026&pitch_type=FF"
    ).json["overall"]
    assert only_fastballs["batted_ball_type_count"] == 0
    assert all(only_fastballs[key] is None for key in ("gb_pct", "fb_pct", "ld_pct", "pu_pct"))

    only_early_count = profile_client.get(
        f"/api/v1/pitchers/{PITCHER_ID}/profile?season=2026&balls=1&strikes=0"
    ).json["overall"]
    assert all(only_early_count[key] is None for key in ("gb_pct", "fb_pct", "ld_pct", "pu_pct"))


def test_pitch_shape_vs_avg_uses_verified_full_mlb_slot_reference(
    profile_client, app, tmp_path, monkeypatch
):
    import csv
    import gzip

    from sqlalchemy import select

    from app.services import movement_reference

    with app.app_context():
        four_seamers = db.session.scalars(select(Pitch).where(Pitch.pitch_type == "FF")).all()
        for pitch in four_seamers:
            pitch.arm_angle = 42.0
        db.session.commit()

    path = tmp_path / "league_movement_2026.csv.gz"
    with gzip.open(path, "wt", newline="", encoding="utf-8") as stream:
        writer = csv.DictWriter(stream, fieldnames=movement_reference.REFERENCE_FIELDS)
        writer.writeheader()
        writer.writerows(
            {
                "pitcher_id": pitcher_id,
                "pitch_type": "FF",
                "hand": "R",
                "arm_angle_bin": 42,
                "pitch_count": 25,
                "hb_sum": -200,
                "ivb_sum": 400,
            }
            for pitcher_id in range(500, 505)
        )
    monkeypatch.setattr(movement_reference, "reference_path", lambda season: path)
    monkeypatch.setattr(
        movement_reference, "compact_reference_path", lambda season: tmp_path / "none.b85"
    )
    movement_reference._load_reference.cache_clear()

    payload = profile_client.get(f"/api/v1/pitchers/{PITCHER_ID}/profile?season=2026").json
    fastball = next(pitch for pitch in payload["arsenal"] if pitch["pitch_type"] == "FF")
    slider = next(pitch for pitch in payload["arsenal"] if pitch["pitch_type"] == "SL")
    assert fastball["hb_vs_avg"] == 0.5
    assert fastball["ivb_vs_avg"] == 0.5
    assert fastball["movement_avg_pitches"] == 125
    assert fastball["movement_joint_pitches"] == 2
    assert slider["hb_vs_avg"] is None
    assert slider["ivb_vs_avg"] is None


def test_spin_axis_circular_average_tracks_coverage_and_filters(profile_client, app):
    with app.app_context():
        for pitch_id, axis in {
            "1001_1_1": 359.0,
            "1001_1_2": 1.0,
            "1002_2_1": 90.0,
            "1002_3_1": 270.0,
        }.items():
            db.session.get(Pitch, pitch_id).spin_axis = axis
        db.session.commit()

    url = f"/api/v1/pitchers/{PITCHER_ID}/profile?season=2026"
    arsenal = {pitch["pitch_type"]: pitch for pitch in profile_client.get(url).json["arsenal"]}
    assert arsenal["FF"]["avg_spin_axis"] == 0.0
    assert arsenal["FF"]["spin_axis_pitch_count"] == 2
    # Two opposite directions do not have a meaningful circular average.
    assert arsenal["SL"]["avg_spin_axis"] is None
    assert arsenal["SL"]["spin_axis_pitch_count"] == 2

    filtered = profile_client.get(url + "&pitch_type=FF&strikes=1").json["arsenal"][0]
    assert filtered["avg_spin_axis"] == 1.0
    assert filtered["spin_axis_pitch_count"] == 1

    righties = profile_client.get(url + "&batter_side=R").json["arsenal"]
    assert [pitch["pitch_type"] for pitch in righties] == ["FF"]

    with app.app_context():
        db.session.get(Pitch, "1001_1_1").description = "automatic_ball"
        db.session.commit()
    physical_only = profile_client.get(url + "&pitch_type=FF").json["arsenal"][0]
    assert physical_only["avg_spin_axis"] == 1.0
    assert physical_only["spin_axis_pitch_count"] == 1


def test_spin_axis_missing_tracking_remains_unavailable(profile_client):
    pitches = profile_client.get(f"/api/v1/pitchers/{PITCHER_ID}/profile").json["arsenal"]
    assert all(pitch["avg_spin_axis"] is None for pitch in pitches)
    assert all(pitch["spin_axis_pitch_count"] == 0 for pitch in pitches)


def test_arm_angle_shape_uses_valid_tracked_pitches_and_active_filters(profile_client, app):
    with app.app_context():
        angles = {
            "1001_1_1": 42.0,
            "1001_1_2": 48.0,
            "1002_2_1": None,
            "1002_3_1": 35.0,
        }
        for pitch_id, angle in angles.items():
            db.session.get(Pitch, pitch_id).arm_angle = angle
        db.session.commit()

    url = f"/api/v1/pitchers/{PITCHER_ID}/profile?season=2026"
    response = profile_client.get(url)
    assert response.status_code == 200
    pitches = {row["pitch_type"]: row for row in response.json["arsenal"]}
    assert pitches["FF"]["avg_arm_angle"] == 45.0
    assert pitches["FF"]["arm_angle_pitch_count"] == 2
    assert pitches["SL"]["avg_arm_angle"] == 35.0
    assert pitches["SL"]["arm_angle_pitch_count"] == 1

    exact_count = profile_client.get(url + "&balls=0&strikes=0").json
    selected = {row["pitch_type"]: row for row in exact_count["arsenal"]}
    assert selected["FF"]["avg_arm_angle"] == 42.0
    assert selected["FF"]["arm_angle_pitch_count"] == 1
    assert selected["SL"]["avg_arm_angle"] is None
    assert selected["SL"]["arm_angle_pitch_count"] == 0

    righties = profile_client.get(url + "&batter_side=R").json
    assert [row["pitch_type"] for row in righties["arsenal"]] == ["FF"]
    assert righties["arsenal"][0]["avg_arm_angle"] == 45.0

    april = profile_client.get(url + "&date_to=2026-04-30").json
    assert april["arsenal"][0]["avg_arm_angle"] == 45.0

    with app.app_context():
        db.session.get(Pitch, "1001_1_2").arm_angle = 125.0
        db.session.commit()
    valid_only = profile_client.get(url + "&pitch_type=FF").json["arsenal"][0]
    assert valid_only["avg_arm_angle"] == 42.0
    assert valid_only["arm_angle_pitch_count"] == 1


def test_arm_angle_shape_unavailable_when_tracking_is_missing(profile_client):
    response = profile_client.get(f"/api/v1/pitchers/{PITCHER_ID}/profile?season=2026")
    assert response.status_code == 200
    for pitch in response.json["arsenal"]:
        assert pitch["avg_arm_angle"] is None
        assert pitch["arm_angle_pitch_count"] == 0


def test_release_height_and_side_are_filter_aware_and_use_separate_coverage(profile_client, app):
    with app.app_context():
        coordinates = {
            "1001_1_1": (-1.4, 5.8),
            "1001_1_2": (None, 6.2),
            "1002_2_1": (2.4, 4.8),
            "1002_3_1": (0.0, None),
        }
        for pitch_id, (side, height) in coordinates.items():
            pitch = db.session.get(Pitch, pitch_id)
            pitch.release_pos_x = side
            pitch.release_pos_z = height
        db.session.commit()

    url = f"/api/v1/pitchers/{PITCHER_ID}/profile?season=2026"
    response = profile_client.get(url)
    assert response.status_code == 200
    arsenal = {pitch["pitch_type"]: pitch for pitch in response.json["arsenal"]}
    assert arsenal["FF"]["avg_release_height"] == 6.0
    assert arsenal["FF"]["release_height_pitch_count"] == 2
    assert arsenal["FF"]["avg_release_side"] == -1.4
    assert arsenal["FF"]["release_side_pitch_count"] == 1
    assert arsenal["SL"]["avg_release_height"] == 4.8
    assert arsenal["SL"]["release_height_pitch_count"] == 1
    assert arsenal["SL"]["avg_release_side"] == 1.2
    assert arsenal["SL"]["release_side_pitch_count"] == 2

    first_count = profile_client.get(url + "&balls=0&strikes=0").json
    filtered = {pitch["pitch_type"]: pitch for pitch in first_count["arsenal"]}
    assert filtered["FF"]["avg_release_height"] == 5.8
    assert filtered["FF"]["avg_release_side"] == -1.4
    assert filtered["SL"]["avg_release_height"] == 4.8
    assert filtered["SL"]["avg_release_side"] == 2.4

    zero_side = profile_client.get(url + "&balls=1&strikes=0").json["arsenal"][0]
    assert zero_side["pitch_type"] == "SL"
    assert zero_side["avg_release_side"] == 0.0
    assert zero_side["release_side_pitch_count"] == 1
    assert zero_side["avg_release_height"] is None
    assert zero_side["release_height_pitch_count"] == 0

    righties = profile_client.get(url + "&batter_side=R").json["arsenal"]
    assert len(righties) == 1
    assert righties[0]["pitch_type"] == "FF"
    assert righties[0]["avg_release_height"] == 6.0

    april = profile_client.get(url + "&date_to=2026-04-30").json["arsenal"]
    assert len(april) == 1
    assert april[0]["avg_release_side"] == -1.4

    with app.app_context():
        db.session.get(Pitch, "1001_1_1").description = "automatic_ball"
        db.session.commit()
    eligible = profile_client.get(url + "&pitch_type=FF").json["arsenal"][0]
    assert eligible["avg_release_height"] == 6.2
    assert eligible["release_height_pitch_count"] == 1
    assert eligible["avg_release_side"] is None
    assert eligible["release_side_pitch_count"] == 0


def test_release_extension_filters_and_automatic_calls(profile_client, app):
    with app.app_context():
        db.session.get(Pitch, "1001_1_1").release_extension = 6.4
        db.session.get(Pitch, "1001_1_2").release_extension = 6.6
        db.session.get(Pitch, "1002_2_1").release_extension = 5.8
        db.session.get(Pitch, "1002_3_1").release_extension = None
        db.session.commit()

    url = f"/api/v1/pitchers/{PITCHER_ID}/profile?season=2026"
    arsenal = {p["pitch_type"]: p for p in profile_client.get(url).json["arsenal"]}
    assert arsenal["FF"]["release_extension"] == 6.5
    assert arsenal["FF"]["release_extension_pitch_count"] == 2
    assert arsenal["SL"]["release_extension"] == 5.8
    assert arsenal["SL"]["release_extension_pitch_count"] == 1

    one_strike = profile_client.get(url + "&pitch_type=FF&strikes=1").json["arsenal"][0]
    assert one_strike["release_extension"] == 6.6
    assert one_strike["release_extension_pitch_count"] == 1

    lefty = profile_client.get(url + "&batter_side=L").json["arsenal"][0]
    assert lefty["release_extension"] == 5.8
    assert lefty["release_extension_pitch_count"] == 1

    with app.app_context():
        db.session.get(Pitch, "1001_1_1").description = "automatic_ball"
        db.session.commit()
    physical = profile_client.get(url + "&pitch_type=FF").json["arsenal"][0]
    assert physical["release_extension"] == 6.6
    assert physical["release_extension_pitch_count"] == 1

    with app.app_context():
        db.session.get(Pitch, "1001_1_2").release_extension = None
        db.session.commit()
    missing = profile_client.get(url + "&pitch_type=FF").json["arsenal"][0]
    assert missing["release_extension"] is None
    assert missing["release_extension_pitch_count"] == 0


def test_release_point_sd_uses_paired_coordinates_by_pitch_type_and_filters(profile_client, app):
    with app.app_context():
        for pitch_id, (side, height) in {
            "1001_1_1": (-1.6, 5.8),
            "1001_1_2": (-2.0, 6.2),
            "1002_2_1": (1.0, 5.0),
            "1002_3_1": (1.0, 5.0),
        }.items():
            pitch = db.session.get(Pitch, pitch_id)
            pitch.release_pos_x = side
            pitch.release_pos_z = height
        db.session.commit()

    response = profile_client.get(f"/api/v1/pitchers/{PITCHER_ID}/profile?season=2026")
    assert response.status_code == 200
    arsenal = {p["pitch_type"]: p for p in response.json["arsenal"]}
    fastball, slider = arsenal["FF"], arsenal["SL"]
    assert fastball["release_point_sd_pitch_count"] == 2
    assert fastball["release_side_sd_inches"] == 3.4
    assert fastball["release_height_sd_inches"] == 3.4
    assert fastball["release_point_sd_inches"] == 4.8
    assert slider["release_point_sd_inches"] == 0.0
    assert slider["release_point_sd_pitch_count"] == 2

    # One pitch does not define a sample standard deviation.
    filtered = profile_client.get(
        f"/api/v1/pitchers/{PITCHER_ID}/profile?season=2026&pitch_type=FF&strikes=1"
    ).json["arsenal"][0]
    assert filtered["release_point_sd_pitch_count"] == 1
    assert filtered["release_point_sd_inches"] is None
    assert filtered["release_side_sd_inches"] is None
    assert filtered["release_height_sd_inches"] is None

    with app.app_context():
        # Do not calculate each axis with a different denominator.
        db.session.get(Pitch, "1001_1_2").release_pos_x = None
        db.session.commit()
    partially_tracked = profile_client.get(
        f"/api/v1/pitchers/{PITCHER_ID}/profile?pitch_type=FF"
    ).json["arsenal"][0]
    assert partially_tracked["release_height_pitch_count"] == 2
    assert partially_tracked["release_side_pitch_count"] == 1
    assert partially_tracked["release_point_sd_pitch_count"] == 1
    assert partially_tracked["release_point_sd_inches"] is None
    assert partially_tracked["release_height_sd_inches"] is None


def test_release_point_sd_excludes_automatic_calls(profile_client, app):
    with app.app_context():
        db.session.get(Pitch, "1001_1_2").description = "automatic_ball"
        db.session.commit()
    fastball = profile_client.get(f"/api/v1/pitchers/{PITCHER_ID}/profile?pitch_type=FF").json[
        "arsenal"
    ][0]
    assert fastball["release_point_sd_pitch_count"] == 1
    assert fastball["release_point_sd_inches"] is None


def test_release_shape_missing_tracking_displays_null_not_zero(profile_client, app):
    with app.app_context():
        for pitch_id in ("1001_1_1", "1001_1_2", "1002_2_1", "1002_3_1"):
            pitch = db.session.get(Pitch, pitch_id)
            pitch.release_pos_x = None
            pitch.release_pos_z = None
        db.session.commit()
    response = profile_client.get(f"/api/v1/pitchers/{PITCHER_ID}/profile?season=2026")
    assert response.status_code == 200
    for pitch in response.json["arsenal"]:
        assert pitch["avg_release_height"] is None
        assert pitch["avg_release_side"] is None
        assert pitch["release_height_pitch_count"] == 0
        assert pitch["release_side_pitch_count"] == 0
        assert pitch["release_point_sd_inches"] is None
        assert pitch["release_point_sd_pitch_count"] == 0
