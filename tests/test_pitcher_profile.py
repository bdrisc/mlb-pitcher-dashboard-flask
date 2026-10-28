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
