"""Two-strike opportunity rates, event attribution, filters and display."""

import pytest

from app.extensions import db
from app.models import Pitch
from tests.test_pitcher_profile import _pitch
from tests.test_pitcher_profile import profile_client as profile_client_fixture

profile_client = profile_client_fixture
URL = "/api/v1/pitchers/100/profile"


@pytest.fixture
def putaway_client(app, profile_client):
    with app.app_context():
        db.session.query(Pitch).delete()
        # Unequal opportunity counts: FF 1/4, SL 2/2, pooled 3/6.
        rows = [
            ("FF", 2, "called_strike", "strikeout"),
            ("FF", 2, "foul", None),
            ("FF", 2, "ball", None),
            ("FF", 2, "hit_into_play", "single"),
            ("SL", 2, "swinging_strike_blocked", "STRIKEOUT"),
            ("SL", 2, "foul_tip", "strikeout_double_play"),
            ("FF", 0, "called_strike", None),
            ("FF", 1, "swinging_strike", None),
            ("SL", 2, "automatic_strike", "strikeout"),
            ("SL", 2, "automatic_ball", "walk"),
        ]
        for n, (code, strikes, description, event) in enumerate(rows, 1):
            db.session.add(
                _pitch(
                    pitch_id=f"putaway_{n}",
                    game_pk=1001 if code == "FF" else 1002,
                    batter_id=200 if code == "FF" else 201,
                    batter_side="R" if code == "FF" else "L",
                    inning_half="Top" if code == "FF" else "Bot",
                    at_bat_number=n,
                    pitch_number=1,
                    balls=0,
                    strikes=strikes,
                    pitch_type=code,
                    pitch_name=code,
                    description=description,
                    events=event,
                )
            )
        db.session.commit()
    return profile_client


def test_putaway_overall_pools_counts_and_attributes_pitch_types(putaway_client):
    data = putaway_client.get(URL).json
    overall = data["overall"]
    assert overall["putaway_pct"] == 50.0
    assert overall["putaway_strikeout_count"] == 3
    assert overall["putaway_pitch_count"] == 6
    arsenal = {p["pitch_type"]: p for p in data["arsenal"]}
    assert arsenal["FF"]["putaway_pct"] == 25.0
    assert arsenal["SL"]["putaway_pct"] == 100.0
    assert overall["putaway_pct"] != (25 + 100) / 2
    assert {p["batter_side"]: p["putaway_pct"] for p in data["platoon_splits"]} == {
        "R": 25.0,
        "L": 100.0,
    }


@pytest.mark.parametrize(
    "query,rate,ks,opportunities",
    [
        ({"pitch_type": "FF"}, 25.0, 1, 4),
        ({"pitch_type": "SL"}, 100.0, 2, 2),
        ({"batter_side": "L"}, 100.0, 2, 2),
        ({"date_from": "2026-05-01"}, 100.0, 2, 2),
        ({"team": "BOS"}, 50.0, 3, 6),
        ({"home_away": "away"}, 100.0, 2, 2),
        ({"balls": 0, "strikes": 2}, 50.0, 3, 6),
        ({"strikes": 1}, None, 0, 0),
    ],
)
def test_putaway_uses_existing_global_filters(putaway_client, query, rate, ks, opportunities):
    data = putaway_client.get(URL, query_string=query).json
    assert data["overall"]["putaway_pct"] == rate
    assert data["overall"]["putaway_strikeout_count"] == ks
    assert data["overall"]["putaway_pitch_count"] == opportunities
    assert sum(p["putaway_pitch_count"] for p in data["arsenal"]) == opportunities
    assert sum(p["putaway_strikeout_count"] for p in data["arsenal"]) == ks


@pytest.mark.parametrize(
    "strikes,description,event,rate,ks,opportunities",
    [
        (2, "called_strike", "strikeout", 100.0, 1, 1),
        (2, "swinging_strike", "strikeout", 100.0, 1, 1),
        (2, "missed_bunt", "strikeout", 100.0, 1, 1),
        (2, "foul_bunt", "strikeout", 100.0, 1, 1),
        (2, "foul", None, 0.0, 0, 1),
        (2, "swinging_strike", None, 0.0, 0, 1),
        (2, None, None, 0.0, 0, 1),
        (2, "AUTOMATIC_STRIKE", "strikeout", None, 0, 0),
        (1, "called_strike", "strikeout", None, 0, 0),
    ],
)
def test_putaway_requires_two_strike_pitch_and_terminal_event(
    app, profile_client, strikes, description, event, rate, ks, opportunities
):
    with app.app_context():
        db.session.query(Pitch).delete()
        db.session.add(
            _pitch(
                pitch_id="only",
                game_pk=1001,
                batter_id=200,
                at_bat_number=1,
                pitch_number=1,
                balls=0,
                strikes=strikes,
                pitch_type="FF",
                pitch_name="Fastball",
                description=description,
                events=event,
            )
        )
        db.session.commit()
    data = profile_client.get(URL).json
    for metrics in [data["overall"], data["arsenal"][0]]:
        assert metrics["putaway_pct"] == rate
        assert metrics["putaway_strikeout_count"] == ks
        assert metrics["putaway_pitch_count"] == opportunities


def test_putaway_display_next_to_swstr_and_grades_last(profile_client):
    html = profile_client.get("/savant-card").get_data(as_text=True)
    assert html.index('data-metric="swstr_pct"') < html.index('data-metric="putaway_pct"')
    assert html.index('data-metric="putaway_pct"') < html.index('data-metric="csw_pct"')
    assert html.index("SwStr%</th>") < html.index("PutAway%</th>") < html.index("CSW</th>")
    from re import findall

    assert findall(r'data-metric="([^"]+)"', html)[-3:] == [
        "stuff_plus",
        "location_plus",
        "pitching_plus",
    ]
