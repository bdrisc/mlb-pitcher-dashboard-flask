"""Two-season API, publisher, and unavailable-reference regression tests."""

from datetime import date, datetime, timezone

import pytest

from app.extensions import db
from app.models import Game, Pitch, Player, PublishedPitchingMetric, SavantActiveSpin


@pytest.fixture
def two_year_client(app):
    now = datetime.now(timezone.utc)
    with app.app_context():
        db.session.add_all(
            [
                Player(mlb_id=123456, player_name="Two Season Pitcher", throws="R"),
                Player(mlb_id=234567, player_name="Test Batter", bats="R"),
                Game(
                    game_pk=2025001,
                    season=2025,
                    game_date=date(2025, 4, 1),
                    game_type="R",
                    home_team="BOS",
                    away_team="NYY",
                ),
                Game(
                    game_pk=2026001,
                    season=2026,
                    game_date=date(2026, 4, 1),
                    game_type="R",
                    home_team="BOS",
                    away_team="NYY",
                ),
            ]
        )
        db.session.flush()
        for season, game_pk, velocity, adj, haaaa in [
            (2025, 2025001, 93.0, None, None),
            (2026, 2026001, 96.0, 0.50, -0.25),
        ]:
            db.session.add(
                Pitch(
                    pitch_id=f"{game_pk}_1_1",
                    game_pk=game_pk,
                    pitcher_id=123456,
                    batter_id=234567,
                    at_bat_number=1,
                    pitch_number=1,
                    pitch_type="FF",
                    pitch_name="Four-Seam Fastball",
                    inning=1,
                    inning_half="Top",
                    batter_side="R",
                    balls=0,
                    strikes=0,
                    velocity=velocity,
                    spin_rate=2350.0,
                    release_pos_x=-1.5,
                    release_pos_z=5.8,
                    plate_x=0.0,
                    plate_z=2.4,
                    zone=5,
                    horizontal_break_inches=-7,
                    vertical_break_inches=16,
                    vaa=-4.5,
                    haa=0.7,
                    vaa_adj=adj,
                    haaaa=haaaa,
                    delta_run_expectancy=-0.05,
                    description="called_strike",
                )
            )
            db.session.add(
                PublishedPitchingMetric(
                    mlb_id=123456,
                    season=season,
                    batter_side="ALL",
                    fip=3.0 if season == 2025 else 4.0,
                    xfip=3.1,
                    siera=3.2,
                    xera=2.9 if season == 2025 else 4.1,
                )
            )
            db.session.add(
                PublishedPitchingMetric(
                    mlb_id=123456,
                    season=season,
                    batter_side="R",
                    fip=3.5,
                    xfip=3.6,
                )
            )
            db.session.add(
                SavantActiveSpin(
                    mlb_id=123456,
                    season=season,
                    pitch_type="FF",
                    active_spin_pct=90.0 if season == 2025 else 80.0,
                    updated_at=now,
                )
            )
        db.session.commit()
    return app.test_client()


def test_year_switch_keeps_2026_values_identical(two_year_client):
    url = "/api/v1/pitchers/123456/profile?season={}"
    first_2026 = two_year_client.get(url.format(2026))
    year_2025 = two_year_client.get(url.format(2025))
    second_2026 = two_year_client.get(url.format(2026))
    assert first_2026.status_code == year_2025.status_code == second_2026.status_code == 200
    assert first_2026.json == second_2026.json
    assert first_2026.json["sample"]["pitches"] == 1
    assert year_2025.json["sample"]["pitches"] == 1
    assert first_2026.json["overall"]["fip"] == 4.0
    assert year_2025.json["overall"]["fip"] == 3.0
    assert first_2026.json["overall"]["xera"] == 4.1
    assert year_2025.json["overall"]["xera"] == 2.9
    assert first_2026.json["arsenal"][0]["spin_efficiency_pct"] == 80.0
    assert year_2025.json["arsenal"][0]["spin_efficiency_pct"] == 90.0
    assert first_2026.json["overall"]["vaa_adj"] == 0.5
    assert first_2026.json["overall"]["haaaa"] == -0.25
    assert year_2025.json["overall"]["vaa_adj"] is None
    assert year_2025.json["overall"]["haaaa"] is None
    assert year_2025.json["arsenal"][0]["vaa_adj"] is None
    assert year_2025.json["arsenal"][0]["haaaa"] is None


def test_year_switch_filters_charts_and_hand_references(two_year_client):
    directory = two_year_client.get("/api/v1/pitchers")
    assert directory.status_code == 200
    pitcher = next(p for p in directory.json["pitchers"] if p["mlb_id"] == 123456)
    assert pitcher["seasons"] == [2026, 2025]
    for year in (2025, 2026):
        charts = two_year_client.get(f"/api/v1/pitchers/123456/charts?season={year}")
        assert charts.status_code == 200
        assert charts.json["sample"]["pitches"] == 1
        assert charts.json["query"]["season"] == year
        profile = two_year_client.get(
            f"/api/v1/pitchers/123456/profile?season={year}&batter_side=R"
        )
        assert profile.status_code == 200
        assert profile.json["overall"]["reference_batter_side"] == "R"
        assert profile.json["overall"]["xera"] is None
        assert profile.json["overall"]["fip"] == 3.5
