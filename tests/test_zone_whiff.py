"""In-zone whiff rates share the report's swing and location rules."""

import pytest

from app.extensions import db
from app.models import Pitch
from tests.test_pitcher_profile import _pitch
from tests.test_pitcher_profile import profile_client as profile_client_fixture

profile_client = profile_client_fixture
URL = "/api/v1/pitchers/100/profile"


@pytest.fixture
def zone_client(app, profile_client):
    with app.app_context():
        db.session.query(Pitch).delete()
        rows = [
            ("FF", "swinging_strike", True, 5, True, 2),
            ("FF", "foul_tip", True, 5, True, 2),
            ("FF", "foul", True, 5, True, 0),
            ("FF", "hit_into_play", True, None, True, 0),  # geometry fallback
            ("FF", "foul", True, 5, True, 0),
            ("FF", "called_strike", True, 5, True, 2),
            ("FF", "swinging_strike_blocked", False, 12, True, 2),
            ("FF", "swinging_strike", True, None, False, 2),  # no known location
            ("SL", "missed_bunt", True, 5, True, 2),
            ("CH", "swinging_strike", False, 12, True, 2),
            ("SI", "foul", True, 5, True, 0),
            ("FF", "foul", False, 12, True, 0),
            ("FF", "ball", False, 12, True, 2),
            ("FF", "swinging_strike", False, None, False, 2),  # unknown is not outside
        ]
        for n, (code, description, in_zone, zone, geometry, strikes) in enumerate(rows, 1):
            db.session.add(
                _pitch(
                    pitch_id=f"zone_whiff_{n}",
                    game_pk=1001,
                    batter_id=200,
                    at_bat_number=n,
                    pitch_number=1,
                    balls=0,
                    strikes=strikes,
                    pitch_type=code,
                    pitch_name=code,
                    description=description,
                    is_in_zone=in_zone,
                    zone=zone,
                    plate_x=0 if geometry else None,
                    batter_side="L" if code == "SL" else "R",
                )
            )
        db.session.commit()
    return profile_client


def test_zone_whiff_uses_known_in_zone_swings_and_pooled_counts(zone_client):
    data = zone_client.get(URL).json
    assert data["overall"]["zone_whiff_count"] == 3
    assert data["overall"]["zone_swing_count"] == 7
    assert data["overall"]["zone_whiff_pct"] == 42.9
    rows = {row["pitch_type"]: row for row in data["arsenal"]}
    assert rows["FF"]["zone_whiff_pct"] == 40.0
    assert rows["SL"]["zone_whiff_pct"] == 100.0
    assert rows["CH"]["zone_whiff_pct"] is None
    assert rows["SI"]["zone_whiff_pct"] == 0.0
    assert data["overall"]["whiff_pct"] == 58.3


@pytest.mark.parametrize(
    "query,whiffs,swings,rate",
    [
        ("count_group=two_strikes", 3, 3, 100.0),
        ("count_group=two_strikes&pitch_type=FF&batter_side=R", 2, 2, 100.0),
        ("pitch_type=SL&batter_side=L", 1, 1, 100.0),
        ("balls=0&strikes=0", 0, 4, 0.0),
        ("pitch_type=CH", 0, 0, None),
    ],
)
def test_zone_whiff_applies_active_filters(zone_client, query, whiffs, swings, rate):
    overall = zone_client.get(f"{URL}?{query}").json["overall"]
    assert overall["zone_whiff_count"] == whiffs
    assert overall["zone_swing_count"] == swings
    assert overall["zone_whiff_pct"] == rate


def test_out_of_zone_whiff_pools_chase_swings_and_excludes_unknown_locations(zone_client):
    data = zone_client.get(URL).json
    overall = data["overall"]
    assert overall["out_of_zone_whiff_count"] == 2
    assert overall["out_of_zone_swing_count"] == 3
    assert overall["out_of_zone_whiff_pct"] == 66.7
    rows = {row["pitch_type"]: row for row in data["arsenal"]}
    assert rows["FF"]["out_of_zone_whiff_pct"] == 50.0
    assert rows["CH"]["out_of_zone_whiff_pct"] == 100.0
    assert rows["SL"]["out_of_zone_whiff_pct"] is None


@pytest.mark.parametrize(
    "query,whiffs,swings,rate",
    [
        ("count_group=two_strikes&pitch_type=FF&batter_side=R", 1, 1, 100.0),
        ("balls=0&strikes=0", 0, 1, 0.0),
        ("pitch_type=SL&batter_side=L", 0, 0, None),
    ],
)
def test_out_of_zone_whiff_respects_filters_and_zero_opportunities(
    zone_client, query, whiffs, swings, rate
):
    overall = zone_client.get(f"{URL}?{query}").json["overall"]
    assert overall["out_of_zone_whiff_count"] == whiffs
    assert overall["out_of_zone_swing_count"] == swings
    assert overall["out_of_zone_whiff_pct"] == rate
