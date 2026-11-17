"""Verify official pitch-type refresh cannot overwrite unrelated pitch metrics."""

from datetime import date

import pandas as pd
import pytest
from sqlalchemy import select

from app.extensions import db
from app.models import Game, Pitch, Player
from app.services.pitch_type_refresh import (
    PitchTypeSourceError,
    plan_pitch_type_changes,
    refresh_pitch_types,
    validate_pitch_type_source,
)


def _source():
    return pd.DataFrame(
        [
            {
                "game_pk": 823001,
                "at_bat_number": 1,
                "pitch_number": 1,
                "pitcher": 592332,
                "pitch_type": "ST",
            },
            {
                "game_pk": 823001,
                "at_bat_number": 1,
                "pitch_number": 2,
                "pitcher": 592332,
                "pitch_type": "FF",
            },
        ]
    )


def test_savant_pitch_type_source_requires_complete_unique_own_pitch_ids():
    expected = validate_pitch_type_source(_source(), 592332)
    assert expected == {"823001_1_1": "ST", "823001_1_2": "FF"}
    with pytest.raises(PitchTypeSourceError, match="duplicated"):
        validate_pitch_type_source(pd.concat([_source()] * 2), 592332)
    with pytest.raises(PitchTypeSourceError, match="another pitcher"):
        validate_pitch_type_source(_source(), 668909)


def test_pitch_type_plan_refuses_partial_ids_and_only_changes_classifications():
    existing = [("823001_1_1", "SL"), ("823001_1_2", "FF")]
    official = validate_pitch_type_source(_source(), 592332)
    assert plan_pitch_type_changes(existing, official) == [
        {"pitch_id": "823001_1_1", "pitch_type": "ST", "pitch_name": "Sweeper"}
    ]
    with pytest.raises(PitchTypeSourceError, match="do not match"):
        plan_pitch_type_changes(existing, {"823001_1_1": "ST"})
    assert plan_pitch_type_changes(existing, {"823001_1_1": None, "823001_1_2": "FF"}) == []


def test_source_extra_rows_are_ignored_but_missing_local_ids_still_fail():
    existing = [("823001_1_1", "SL"), ("823001_1_2", "FF")]
    source = {
        "823001_1_1": "ST",
        "823001_1_2": "FF",
        "823001_1_3": "CU",
    }
    assert plan_pitch_type_changes(existing, source) == [
        {"pitch_id": "823001_1_1", "pitch_type": "ST", "pitch_name": "Sweeper"}
    ]
    with pytest.raises(PitchTypeSourceError, match="missing=1"):
        plan_pitch_type_changes(existing, {"823001_1_1": "ST", "823001_1_3": "CU"})
    with pytest.raises(PitchTypeSourceError, match="extra=4"):
        plan_pitch_type_changes(
            existing,
            {**source, "source_extra_1": "FF", "source_extra_2": "FF", "source_extra_3": "FF"},
        )


def test_large_curve_to_knuckle_curve_source_relabel_is_allowed():
    # Reproduces the 2026 Gavin Williams source-vintage shift:
    # 665 local CU and 851 ST; official: 664 KC and 852 ST.
    existing = [
        (f"829991_1_{i}", "CU" if i <= 665 else "ST" if i <= 1516 else "FF") for i in range(1, 2961)
    ]
    official = {
        pitch_id: ("KC" if i <= 664 else "ST" if i == 665 else original)
        for i, (pitch_id, original) in enumerate(existing, start=1)
    }
    official.update({f"829991_2_{i}": "KC" for i in range(1, 32)})
    updates = plan_pitch_type_changes(existing, official)
    assert len(updates) == 665
    assert sum(item["pitch_type"] == "KC" for item in updates) == 664
    assert sum(item["pitch_type"] == "ST" for item in updates) == 1
    assert all(item["pitch_name"] == "Knuckle Curve" for item in updates[:664])


def test_large_arbitrary_reclassification_still_rejected():
    existing = [(f"829991_1_{i}", "CU" if i <= 665 else "FF") for i in range(1, 2961)]
    official = {
        pitch_id: ("SL" if i <= 665 else current)
        for i, (pitch_id, current) in enumerate(existing, start=1)
    }
    with pytest.raises(PitchTypeSourceError, match="exceed the safety cap"):
        plan_pitch_type_changes(existing, official)


def test_large_curve_relabel_rejects_many_unrelated_edits_and_excess_extras():
    existing = [(f"829991_1_{i}", "CU" if i <= 665 else "FF") for i in range(1, 2961)]
    official = {
        pitch_id: ("KC" if i <= 600 else "SL" if i <= 665 else original)
        for i, (pitch_id, original) in enumerate(existing, start=1)
    }
    with pytest.raises(PitchTypeSourceError, match="exceed the safety cap"):
        plan_pitch_type_changes(existing, official)
    official = {
        pitch_id: ("KC" if i <= 665 else original)
        for i, (pitch_id, original) in enumerate(existing, start=1)
    }
    official.update({f"829991_2_{i}": "FF" for i in range(1, 70)})
    with pytest.raises(PitchTypeSourceError, match="extra=69"):
        plan_pitch_type_changes(existing, official)


def test_pitch_type_refresh_dry_run_then_updates_only_names_and_codes(app, monkeypatch):
    with app.app_context():
        db.session.add(Player(mlb_id=592332, player_name="Pitch Type Refresh Test"))
        db.session.add(
            Game(
                game_pk=823001,
                season=2026,
                game_date=date(2026, 8, 2),
                home_team="BOS",
                away_team="NYY",
            )
        )
        db.session.flush()
        for number, pitch_type in [(1, "SL"), (2, "FF")]:
            db.session.add(
                Pitch(
                    pitch_id=f"823001_1_{number}",
                    game_pk=823001,
                    pitcher_id=592332,
                    batter_id=592332,
                    at_bat_number=1,
                    pitch_number=number,
                    pitch_type=pitch_type,
                    pitch_name="Slider" if number == 1 else "Four-Seam Fastball",
                    balls=0,
                    strikes=0,
                    velocity=91.5,
                    arm_angle=39.4,
                    delta_run_expectancy=-0.123,
                )
            )
        db.session.commit()
        monkeypatch.setattr(
            "app.services.pitch_type_refresh.fetch_pitch_type_source",
            lambda job: validate_pitch_type_source(_source(), 592332),
        )
        dry = refresh_pitch_types(pitcher_id=592332, season=2026, apply=False)
        assert dry["verified"] == 1 and dry["changed_pitches"] == 1
        assert db.session.get(Pitch, "823001_1_1").pitch_type == "SL"
        done = refresh_pitch_types(pitcher_id=592332, season=2026, apply=True)
        assert done["verified"] == 1 and done["changed_pitches"] == 1
        db.session.expire_all()
        pitch = db.session.scalar(select(Pitch).where(Pitch.pitch_id == "823001_1_1"))
        assert pitch.pitch_type == "ST" and pitch.pitch_name == "Sweeper"
        assert pitch.velocity == pytest.approx(91.5)
        assert pitch.arm_angle == pytest.approx(39.4)
        assert pitch.delta_run_expectancy == pytest.approx(-0.123)
