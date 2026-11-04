from itertools import product

import pytest

from app.extensions import db
from app.models import Pitch
from tests.test_pitcher_profile import _pitch
from tests.test_pitcher_profile import profile_client as profile_client_fixture

profile_client = profile_client_fixture
BASE = "/api/v1/pitchers/100"


@pytest.fixture
def count_client(app, profile_client):
    with app.app_context():
        db.session.query(Pitch).delete()
        for n, (balls, strikes) in enumerate(product(range(4), range(3)), 1):
            full_count = (balls, strikes) == (3, 2)
            db.session.add(
                _pitch(
                    pitch_id=f"count_{n}",
                    game_pk=1001,
                    batter_id=201 if full_count else 200,
                    batter_side="L" if full_count else "R",
                    at_bat_number=n,
                    pitch_number=1,
                    balls=balls,
                    strikes=strikes,
                    pitch_type="SL" if full_count else "FF",
                    description="swinging_strike" if full_count else "ball",
                    events="strikeout" if full_count else None,
                )
            )
        db.session.commit()
    return profile_client


@pytest.mark.parametrize(
    "query,counts",
    [
        ("count_group=ahead", {"0-1", "0-2", "1-2"}),
        ("count_group=behind", {"1-0", "2-0", "2-1", "3-0", "3-1"}),
        ("count_group=even", {"0-0", "1-1", "2-2"}),
        ("count_group=two_strikes", {"0-2", "1-2", "2-2", "3-2"}),
        ("balls=3&strikes=2", {"3-2"}),
        ("count_group=two_strikes&pitch_type=SL&batter_side=L", {"3-2"}),
    ],
)
def test_groups_filter_profiles_and_charts(count_client, query, counts):
    profile = count_client.get(f"{BASE}/profile?{query}")
    charts = count_client.get(f"{BASE}/charts?{query}")
    assert profile.status_code == charts.status_code == 200
    assert profile.json["sample"]["pitches"] == charts.json["sample"]["pitches"] == len(counts)
    assert profile.json["overall"]["putaway_pitch_count"] == sum(c.endswith("-2") for c in counts)
    assert profile.json["overall"]["putaway_strikeout_count"] == int("3-2" in counts)
    assert {row["count"] for row in charts.json["charts"]["usage_by_count"]["rows"]} == counts


@pytest.mark.parametrize(
    "query",
    ["count_group=bad", "count_group=ahead&count_group=even", "count_group=ahead&strikes=2"],
)
def test_invalid_count_group_returns_validation_error(profile_client, query):
    response = profile_client.get(f"{BASE}/profile?{query}")
    assert response.status_code == 400
    assert "count_group" in response.json["details"]
