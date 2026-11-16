"""A revised official hit must not leave local season wOBA missing."""

from datetime import date

import pytest

from app.extensions import db
from app.models import Game, Pitch, Player
from app.services.woba_refresh import reconcile_revised_woba_outcomes


def test_revised_outcome_dry_run_and_safe_apply(app, monkeypatch):
    with app.app_context():
        db.session.add(Player(mlb_id=797001, player_name="Revised Outcome Test"))
        db.session.add(
            Game(
                game_pk=899991,
                game_date=date(2026, 9, 24),
                season=2026,
                home_team="BOS",
                away_team="CLE",
            )
        )
        db.session.flush()
        pitch = Pitch(
            pitch_id="899991_34_5",
            game_pk=899991,
            pitcher_id=797001,
            batter_id=797001,
            at_bat_number=34,
            pitch_number=5,
            pitch_type="FF",
            pitch_name="Four-Seam Fastball",
            balls=1,
            strikes=2,
            events="field_error",
            description="hit_into_play",
            velocity=95.1,
            arm_angle=39.4,
            estimated_woba=0.351,
            delta_run_expectancy=0.43,
        )
        db.session.add(pitch)
        db.session.commit()
        monkeypatch.setattr(
            "app.services.woba_refresh.fetch_woba_outcomes",
            lambda job: {"899991_34_5": ("single", 0.890088, 1)},
        )
        preview = reconcile_revised_woba_outcomes(pitcher_id=797001, season=2026, apply=False)
        assert preview["revised_outcomes"] == 1
        assert preview["revisions"][0] == {
            "pitch_id": "899991_34_5",
            "from": "field_error",
            "to": "single",
        }
        assert db.session.get(Pitch, pitch.pitch_id).events == "field_error"
        applied = reconcile_revised_woba_outcomes(pitcher_id=797001, season=2026, apply=True)
        assert applied["applied"] and applied["revised_outcomes"] == 1
        db.session.expire_all()
        restored = db.session.get(Pitch, "899991_34_5")
        assert restored.events == "single"
        assert restored.savant_woba_numerator == pytest.approx(0.890088)
        assert restored.savant_woba_denominator == 1
        assert restored.velocity == pytest.approx(95.1)
        assert restored.arm_angle == pytest.approx(39.4)
        assert restored.estimated_woba == pytest.approx(0.351)
        assert restored.delta_run_expectancy == pytest.approx(0.43)
        assert restored.pitch_type == "FF"
        assert (
            reconcile_revised_woba_outcomes(pitcher_id=797001, season=2026, apply=False)[
                "revised_outcomes"
            ]
            == 0
        )


def test_revised_outcome_refuses_foreign_pitch_ids(app, monkeypatch):
    with app.app_context():
        db.session.add(Player(mlb_id=797002, player_name="Wrong Source Test"))
        db.session.add(
            Game(
                game_pk=899992,
                game_date=date(2026, 9, 24),
                season=2026,
                home_team="BOS",
                away_team="CLE",
            )
        )
        db.session.add(
            Pitch(
                pitch_id="899992_2_1",
                game_pk=899992,
                pitcher_id=797002,
                batter_id=797002,
                at_bat_number=2,
                pitch_number=1,
                pitch_type="FF",
                balls=0,
                strikes=0,
                events="field_error",
            )
        )
        db.session.commit()
        monkeypatch.setattr(
            "app.services.woba_refresh.fetch_woba_outcomes",
            lambda job: {"wrong_pitch": ("single", 0.890088, 1)},
        )
        with pytest.raises(ValueError, match="absent from local"):
            reconcile_revised_woba_outcomes(pitcher_id=797002, season=2026, apply=True)
        assert db.session.get(Pitch, "899992_2_1").events == "field_error"
