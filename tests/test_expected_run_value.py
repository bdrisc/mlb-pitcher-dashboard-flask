"""Contact-adjusted expected run value keeps the exact Savant RV comparison paired."""

from datetime import date

import pytest
from sqlalchemy import select

from app.extensions import db
from app.models import Game, Pitch, Player
from app.services.expected_run_value import WOBA_SCALES, expected_run_value_columns
from app.services.pitcher_profiles import _metric_columns, _performance_metrics


def load_sample():
    db.session.add(Player(mlb_id=101, player_name="xRV Example"))
    db.session.add(
        Game(
            game_pk=12,
            season=2026,
            game_date=date(2026, 6, 1),
            home_team="BOS",
            away_team="NYY",
        )
    )
    db.session.flush()
    samples = [
        ("ball", None, 0.1, None, None, None),
        ("hit_into_play", "field_out", -0.3, 0.0, 0.4, 0.0),
        ("hit_into_play_score", "home_run", 1.1, 2.079, 0.6, None),
        ("hit_into_play", "field_out", -0.2, 0.0, None, None),
        ("hit_into_play", "sac_bunt", -0.05, 0.0, 0.3, None),
        ("automatic_ball", None, 0.2, None, None, None),
        ("called_strike", None, None, None, None, None),
    ]
    for number, (description, event, rv, woba, xwoba, verified) in enumerate(samples, 1):
        db.session.add(
            Pitch(
                pitch_id=f"12_1_{number}",
                game_pk=12,
                pitcher_id=101,
                batter_id=101,
                at_bat_number=1,
                pitch_number=number,
                pitch_type="FF",
                balls=0,
                strikes=0,
                description=description,
                events=event,
                delta_run_expectancy=rv,
                woba_value=woba,
                estimated_woba=xwoba,
                savant_woba_numerator=verified,
            )
        )
    db.session.commit()


def test_expected_value_only_replaces_outcomes_on_tracked_contact(app):
    with app.app_context():
        load_sample()
        record = (
            db.session.execute(
                select(*expected_run_value_columns())
                .select_from(Pitch)
                .join(Game, Game.game_pk == Pitch.game_pk)
            )
            .mappings()
            .one()
        )

        assert record["xrv_scored_pitches"] == 3
        assert record["xrv_missing_contact"] == 2
        assert record["xrv_unsupported_contact"] == 1
        assert record["xrv_missing_actual"] == 1
        assert record["xrv_unknown_scale"] == 0
        assert record["xrv_imported_weight_mismatch"] == 1
        assert record["xrv_paired_actual"] == pytest.approx(-0.9)
        # Non-contact ball value is identical in the actual and expected totals.
        correction = (0.0 - 0.4 + 2.049 - 0.6) / WOBA_SCALES[2026]
        assert record["xrv_paired_expected"] == pytest.approx(-0.9 + correction)


def test_per_100_and_gap_use_the_same_paired_pitch_population(app):
    with app.app_context():
        load_sample()
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
        delta = (0.4 - 2.049 + 0.6) / WOBA_SCALES[2026]

        assert metrics["run_value_denominator"] == 6
        assert metrics["expected_run_value_pitch_count"] == 3
        assert metrics["expected_run_value_coverage_pct"] == 50.0
        assert metrics["expected_run_value_unscored_contact"] == 2
        assert metrics["expected_run_value_imported_weight_mismatch"] == 1
        assert metrics["expected_run_value_unsupported_contact"] == 1
        assert metrics["paired_actual_run_value"] == pytest.approx(-0.9)
        assert metrics["run_value_minus_expected"] == pytest.approx(round(delta, 3))
        assert metrics["run_value_minus_expected_per_100"] == pytest.approx(
            round(delta * 100 / 3, 1), abs=0.1
        )
        assert metrics["expected_run_value"] == pytest.approx(round(-0.9 - delta, 3), abs=0.001)


def test_no_source_run_values_yield_null_expectations(app):
    with app.app_context():
        load_sample()
        db.session.query(Pitch).update({Pitch.delta_run_expectancy: None})
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
        assert metrics["expected_run_value"] is None
        assert metrics["expected_run_value_per_100"] is None
        assert metrics["run_value_minus_expected"] is None
        assert metrics["expected_run_value_pitch_count"] == 0
