"""Actual wOBA uses verified Savant components on the filtered pitch sample."""

import pytest
from sqlalchemy import select

from app.extensions import db
from app.models import Pitch
from app.services.woba_refresh import refresh_woba, verify_woba_outcomes
from tests.test_pitcher_profile import profile_client as profile_client_fixture

profile_client = profile_client_fixture
URL = "/api/v1/pitchers/100/profile"


def test_savant_exact_weights_reproduce_published_nola_woba():
    # 2026 regular season, Statcast Search: Nola (605400), 744 PA, .346 wOBA.
    rows = []
    for event, weight, eligible, count in (
        ("single", 0.890088, 1, 105),
        ("double", 1.26144, 1, 32),
        ("triple", 1.59566, 1, 3),
        ("home_run", 2.0494, 1, 37),
        ("walk", 0.698223, 1, 57),
        ("hit_by_pitch", 0.729169, 1, 2),
        ("field_out", 0, 1, 504),
        ("sac_bunt", 0, 0, 2),
        ("intent_walk", 0, 0, 2),
    ):
        for _ in range(count):
            rows.append(
                dict(
                    pitcher=605400,
                    game_year=2026,
                    is_pa=1,
                    game_pk=1,
                    at_bat_number=len(rows) + 1,
                    pitch_number=1,
                    events=event,
                    fangraphs_woba_numer=weight,
                    fangraphs_woba_denom=eligible,
                )
            )
    official = [{"pa": 744, "woba_value": 255.697149, "woba": 0.346}]
    assert len(verify_woba_outcomes(rows, official, 605400, 2026)) == 744
    rows[0]["fangraphs_woba_numer"] = 0.9
    with pytest.raises(ValueError, match="differ from Savant"):
        verify_woba_outcomes(rows, official, 605400, 2026)


def test_woba_backfill_preserves_pitches_and_applies_filters(app, profile_client, monkeypatch):
    with app.app_context():
        rows = list(db.session.scalars(select(Pitch).order_by(Pitch.pitch_id)))
        for pitch in rows:
            pitch.events = None
        single, out, bunt, truncated = rows[:4]
        for pitch, event in zip(
            (single, out, bunt, truncated),
            ("single", "strikeout", "sac_bunt", "truncated_pa"),
            strict=True,
        ):
            pitch.events = event
        single.batter_side = "L"
        out.batter_side = "R"
        single.woba_value = 0.9
        bunt.batter_side = "R"
        db.session.commit()
        outcomes = {
            single.pitch_id: ("single", 0.890088, 1),
            out.pitch_id: ("strikeout", 0, 1),
            bunt.pitch_id: ("sac_bunt", 0, 0),
        }
        assert profile_client.get(URL).json["overall"]["woba_against"] is None
        monkeypatch.setattr("app.services.woba_refresh.fetch_woba_outcomes", lambda _: outcomes)
        result = refresh_woba(season=2026)
        assert result["failed"] == []
        assert result["updated_outcomes"] == 3
        assert refresh_woba(season=2026)["updated_outcomes"] == 0
        assert db.session.get(Pitch, single.pitch_id).woba_value == 0.9
        assert len(list(db.session.scalars(select(Pitch)))) == len(rows)

    overall = profile_client.get(URL).json["overall"]
    assert overall["woba_against"] == 0.445
    assert overall["woba_denominator"] == 2
    assert overall["woba_pending_outcomes"] == 0
    assert profile_client.get(URL + "?batter_side=L").json["overall"]["woba_against"] == 0.890
    assert profile_client.get(URL + "?batter_side=R").json["overall"]["woba_against"] == 0
