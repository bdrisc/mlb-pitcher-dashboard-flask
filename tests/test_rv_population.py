"""Physical-pitch RV accounting is identical for numerator and denominator."""

from datetime import date

import pytest
from sqlalchemy import select

from app.extensions import db
from app.models import Game, Pitch, Player
from app.services.pitcher_profiles import _metric_columns, _performance_metrics


def test_actual_rv_does_not_count_unknown_or_automatic_pitch_values(app):
    with app.app_context():
        db.session.add(Player(mlb_id=739101, player_name="RV Population Audit"))
        db.session.add(
            Game(
                game_pk=123045,
                season=2026,
                game_date=date(2026, 7, 1),
                home_team="BOS",
                away_team="NYY",
            )
        )
        db.session.flush()

        examples = [
            ("FF", "called_strike", -0.1),
            ("SI", "ball", 0.2),
            ("UN", "ball", 0.4),
            ("FF", "automatic_ball", 0.5),
            ("FF", "called_strike", None),
        ]
        for index, (pitch_type, description, actual) in enumerate(examples, 1):
            db.session.add(
                Pitch(
                    pitch_id=f"123045_1_{index}",
                    game_pk=123045,
                    pitcher_id=739101,
                    batter_id=739101,
                    at_bat_number=1,
                    pitch_number=index,
                    pitch_type=pitch_type,
                    description=description,
                    delta_run_expectancy=actual,
                    balls=0,
                    strikes=0,
                )
            )
        db.session.commit()
        record = (
            db.session.execute(
                select(*_metric_columns())
                .select_from(Pitch)
                .join(Game, Game.game_pk == Pitch.game_pk)
            )
            .mappings()
            .one()
        )
        metrics = _performance_metrics(record)

        assert metrics["run_value_denominator"] == 3
        assert metrics["run_value_pitch_count"] == 2
        # The physical-pitch population contains an untracked RV outcome:
        # a partial sum must not masquerade as a complete RV/100.
        assert metrics["run_value"] is None
        assert metrics["run_value_per_100"] is None
        assert metrics["run_value_coverage_pct"] == pytest.approx(66.7)
        assert metrics["paired_actual_run_value"] == pytest.approx(-0.1)
        assert metrics["expected_run_value"] == pytest.approx(-0.1)
