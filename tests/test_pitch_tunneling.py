"""Independent geometry, genuine sequencing, second-pitch filters and coverage."""

import math

import pytest

from app.extensions import db
from app.models import Pitch
from app.services.pitch_tunneling import FRONT_Y, TUNNEL_Y, pair_metrics, pitch_geometry
from tests.test_pitcher_profile import _pitch
from tests.test_pitcher_profile import profile_client as profile_client_fixture

profile_client = profile_client_fixture
URL = "/api/v1/pitchers/100/profile"


def straight(**changes):
    return dict(
        season=2026,
        plate_x=0.0,
        plate_z=2.5,
        vx0=0.0,
        vy0=-100.0,
        vz0=0.0,
        ax=0.0,
        ay=0.0,
        az=0.0,
        release_pos_x=0.0,
        release_pos_y=55.0,
        release_pos_z=2.5,
        **changes,
    )


def test_known_distances_zero_and_actual_release_to_plate_flight_time():
    a = pitch_geometry(straight())
    b = pitch_geometry({**straight(), "plate_x": 0.25, "release_pos_x": 0.25})
    values = pair_metrics(a, b)
    assert values["tunnel_gap_inches"] == values["plate_gap_inches"] == 3
    assert values["release_gap_inches"] == 3
    assert values["flight_time_gap_ms"] == 0
    assert pair_metrics(a, a) == dict.fromkeys(values, 0)
    c = pitch_geometry({**straight(), "release_pos_y": 54})
    assert pair_metrics(a, c)["release_gap_inches"] == 12
    assert pair_metrics(a, c)["flight_time_gap_ms"] == pytest.approx(10)
    assert a["flight"] == pytest.approx((55 - FRONT_Y) / 100)
    assert TUNNEL_Y == pytest.approx(FRONT_Y + 23.8)


def synthetic(season):
    # Independently bisect the full position curve, including negative times
    # before the y=50-ft velocity reference. No production time solver is used.
    def point(t):
        return (-1.6 + 5 * t - 6 * t * t, 50 - 130 * t + 12.5 * t * t, 6 + 3 * t - 10 * t * t)

    def at_y(y):
        lo, hi = -0.1, 0.6
        for _ in range(75):
            t = (lo + hi) / 2
            if point(t)[1] > y:
                lo = t
            else:
                hi = t
        return t, point(t)

    anchor = at_y(17 / 24 if season >= 2026 else FRONT_Y)[1]
    release_time, release = at_y(55)
    front_time, front = at_y(FRONT_Y)
    _, tunnel = at_y(TUNNEL_Y)
    row = dict(
        season=season,
        plate_x=anchor[0],
        plate_z=anchor[2],
        vx0=5,
        vy0=-130,
        vz0=3,
        ax=-12,
        ay=25,
        az=-20,
        release_pos_x=release[0],
        release_pos_y=release[1],
        release_pos_z=release[2],
    )
    return row, {
        "plate": (front[0], front[2]),
        "tunnel": (tunnel[0], tunnel[2]),
        "flight": front_time - release_time,
    }


@pytest.mark.parametrize("season", [2025, 2026])
def test_trajectory_matches_independent_solution_and_both_plate_planes(season):
    row, expected = synthetic(season)
    got = pitch_geometry(row)
    for key, value in expected.items():
        assert got[key] == pytest.approx(value, abs=1e-12)
    other = pitch_geometry(synthetic(2026 if season == 2025 else 2025)[0])
    assert pair_metrics(got, other)["tunnel_gap_inches"] == pytest.approx(0, abs=1e-11)
    assert pair_metrics(got, other)["plate_gap_inches"] == pytest.approx(0, abs=1e-11)


@pytest.mark.parametrize(
    "changes",
    [
        {"plate_x": None},
        {"plate_z": math.nan},
        {"vx0": math.inf},
        {"az": None},
        {"vy0": 100},
        {"ay": 1000},
        {"season": None},
    ],
)
def test_incomplete_or_impossible_geometry_is_unavailable(changes):
    assert pitch_geometry({**straight(), **changes}) is None
    assert pair_metrics(None, pitch_geometry(straight())) is None


def test_partial_release_tracking_does_not_discard_valid_path_metrics():
    a = pitch_geometry(straight())
    b = pitch_geometry({**straight(), "release_pos_x": None})
    values = pair_metrics(a, b)
    assert values["release_gap_inches"] is None
    assert values["tunnel_gap_inches"] == 0
    assert values["flight_time_gap_ms"] == 0
    c = pitch_geometry({**straight(), "release_pos_y": None})
    assert pair_metrics(a, c)["flight_time_gap_ms"] is None
    assert pair_metrics(a, c)["release_gap_inches"] is None


@pytest.fixture
def tunnel_client(app, profile_client):
    with app.app_context():
        db.session.query(Pitch).delete()
        for number, (code, x) in enumerate(
            zip(["FF", "SL", "FF", "SL", "SL"], [0, 0.25, 0.75, 1, 2], strict=True), 1
        ):
            geo = {k: v for k, v in straight().items() if k != "season"}
            geo.update(plate_x=x, release_pos_x=x)
            db.session.add(
                _pitch(
                    pitch_id=f"tunnel_{number}",
                    game_pk=1001,
                    batter_id=200,
                    at_bat_number=1,
                    pitch_number=number,
                    pitch_type=code,
                    pitch_name=code,
                    description="called_strike",
                    batter_side="R",
                    inning_half="Top",
                    balls=0,
                    strikes=1 if number == 2 else 0,
                    **geo,
                )
            )
        db.session.commit()
    return profile_client


def test_ordered_sequences_same_type_pairs_and_weighted_overall(tunnel_client):
    data = tunnel_client.get(URL).json["pitch_tunneling"]
    assert data["method"] == "geometric_fixed_plane_v1"
    assert data["overall"]["observed_pair_count"] == data["overall"]["pair_count"] == 4
    assert data["overall"]["tunnel_gap_inches"] == 6
    pairs = {(p["pitch_a"], p["pitch_b"]): p for p in data["pairs"]}
    assert pairs[("FF", "SL")]["pair_count"] == 2
    assert pairs[("FF", "SL")]["tunnel_gap_inches"] == 3
    assert pairs[("SL", "FF")]["tunnel_gap_inches"] == 6
    assert pairs[("SL", "SL")]["tunnel_gap_inches"] == 12
    types = {p["pitch_type"]: p for p in data["by_pitch_type"]}
    assert types["SL"]["pair_count"] == 3
    assert types["SL"]["tunnel_gap_inches"] == 6
    assert (
        data["overall"]["tunnel_gap_inches"]
        != sum(p["tunnel_gap_inches"] for p in pairs.values()) / 3
    )


def test_pitch_type_and_count_filters_keep_the_real_previous_pitch(tunnel_client):
    data = tunnel_client.get(URL + "?pitch_type=SL").json["pitch_tunneling"]
    assert data["overall"]["pair_count"] == 3
    assert any(p["pitch_a"] == "FF" and p["pitch_b"] == "SL" for p in data["pairs"])
    assert all(p["pitch_b"] == "SL" for p in data["pairs"])
    data = tunnel_client.get(URL + "?pitch_type=SL&strikes=1").json["pitch_tunneling"]
    assert data["overall"]["pair_count"] == 1
    assert data["pairs"][0]["pitch_a"] == "FF"
    assert data["pairs"][0]["tunnel_gap_inches"] == 3
    assert (
        tunnel_client.get(URL + "?pitch_type=FF").json["pitch_tunneling"]["pairs"][0]["pitch_a"]
        == "SL"
    )


def test_missing_rows_or_tracking_never_bridge_sequence_gaps(app, tunnel_client):
    with app.app_context():
        db.session.delete(db.session.get(Pitch, "tunnel_2"))
        db.session.get(Pitch, "tunnel_4").ax = None
        db.session.commit()
    d = tunnel_client.get(URL).json["pitch_tunneling"]
    assert d["overall"]["observed_pair_count"] == 2
    assert d["overall"]["pair_count"] == 0
    assert d["overall"]["missing_geometry_pairs"] == 2
    assert d["overall"]["tunnel_gap_inches"] is None


@pytest.mark.parametrize(
    "change", [{"batter_id": 201}, {"pitcher_id": 200}, {"at_bat_number": 2}, {"game_pk": 1002}]
)
def test_never_pair_across_batter_pitcher_pa_or_game(app, tunnel_client, change):
    with app.app_context():
        row = db.session.get(Pitch, "tunnel_2")
        for k, v in change.items():
            setattr(row, k, v)
        db.session.commit()
    d = tunnel_client.get(URL).json["pitch_tunneling"]
    assert d["overall"]["pair_count"] == 2


@pytest.mark.parametrize("change", [{"description": "automatic_strike"}, {"pitch_type": "UN"}])
def test_automatic_and_unknown_pitches_do_not_create_pairs(app, tunnel_client, change):
    with app.app_context():
        row = db.session.get(Pitch, "tunnel_2")
        for k, v in change.items():
            setattr(row, k, v)
        db.session.commit()
    d = tunnel_client.get(URL).json["pitch_tunneling"]
    assert d["overall"]["observed_pair_count"] == 2


def test_independent_metric_coverage_and_read_only_api(app, tunnel_client):
    before = tunnel_client.get(URL).json
    with app.app_context():
        db.session.get(Pitch, "tunnel_2").release_pos_x = None
        db.session.get(Pitch, "tunnel_5").release_pos_y = None
        db.session.commit()
        rows = db.session.query(Pitch).count()
    after = tunnel_client.get(URL).json
    o = after["pitch_tunneling"]["overall"]
    assert o["pair_count"] == 4
    assert o["metric_pair_counts"]["release_gap_inches"] == 1
    assert o["metric_pair_counts"]["flight_time_gap_ms"] == 3
    assert o["metric_pair_counts"]["tunnel_gap_inches"] == 4
    assert before["overall"] == after["overall"]
    with app.app_context():
        assert db.session.query(Pitch).count() == rows


def test_existing_global_filters_and_empty_sample(tunnel_client):
    for query in ("team=BOS", "home_away=home", "batter_side=R", "date_to=2026-04-01"):
        assert (
            tunnel_client.get(URL + "?" + query).json["pitch_tunneling"]["overall"]["pair_count"]
            == 4
        )
    html = tunnel_client.get("/savant-card").get_data(as_text=True)
    assert 'id="tunneling-body"' in html
    assert (
        html.index('id="separation-heading"')
        < html.index('id="tunneling-heading"')
        < html.index('id="charts-heading"')
    )


def test_only_first_pitches_can_match_filters_without_tunneling_pairs(app, tunnel_client):
    with app.app_context():
        db.session.get(Pitch, "tunnel_1").balls = 3
        db.session.commit()
    payload = tunnel_client.get(URL + "?balls=3").json
    assert payload["sample"]["pitches"] == 1
    data = payload["pitch_tunneling"]
    assert data["pairs"] == [] and data["by_pitch_type"] == []
    assert data["overall"]["observed_pair_count"] == 0
    assert data["overall"]["tunnel_gap_inches"] is None


def test_two_paths_can_cross_at_tunnel_but_separate_at_plate():
    # Straight paths intersect at the chosen tunnel plane. Different lateral
    # velocities then create plate separation; this is not a movement centroid.
    t_tunnel = (50 - TUNNEL_Y) / 100
    t_anchor = (50 - 17 / 24) / 100
    a = pitch_geometry(straight())
    b = pitch_geometry({**straight(), "vx0": 10, "plate_x": 10 * (t_anchor - t_tunnel)})
    gaps = pair_metrics(a, b)
    assert gaps["tunnel_gap_inches"] == pytest.approx(0, abs=1e-12)
    assert gaps["plate_gap_inches"] == pytest.approx(12 * 10 * 23.8 / 100)
