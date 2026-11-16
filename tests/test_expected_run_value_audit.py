"""Independent xRV audit invariants: source precedence, signs, seasons and grouping."""

from datetime import date

import pytest
from sqlalchemy import select

from app.extensions import db
from app.models import Game, Pitch, Player
from app.services.expected_run_value import WOBA_SCALES, expected_run_value_columns


def _snapshot(*conditions):
    record = db.session.execute(
        select(*expected_run_value_columns())
        .select_from(Pitch)
        .join(Game, Game.game_pk == Pitch.game_pk)
        .where(*conditions)
    )
    return record.mappings().one()


def _pitch(
    game_pk,
    pitch_number,
    *,
    pitch_type,
    description,
    event=None,
    rv=None,
    actual=None,
    expected=None,
    verified=None,
):
    return Pitch(
        pitch_id=f"{game_pk}_1_{pitch_number}",
        game_pk=game_pk,
        pitcher_id=801,
        batter_id=801,
        at_bat_number=1,
        pitch_number=pitch_number,
        pitch_type=pitch_type,
        balls=0,
        strikes=0,
        description=description,
        events=event,
        delta_run_expectancy=rv,
        woba_value=actual,
        estimated_woba=expected,
        savant_woba_numerator=verified,
    )


def test_year_specific_scale_verified_weight_and_pitch_type_grouping(app):
    with app.app_context():
        db.session.add(Player(mlb_id=801, player_name="Independent Audit"))
        db.session.add_all(
            [
                Game(
                    game_pk=101,
                    season=2025,
                    game_date=date(2025, 7, 1),
                    home_team="BOS",
                    away_team="NYY",
                ),
                Game(
                    game_pk=102,
                    season=2026,
                    game_date=date(2026, 7, 1),
                    home_team="BOS",
                    away_team="NYY",
                ),
            ]
        )
        db.session.flush()
        db.session.add_all(
            [
                # 2025 uses the published Guts coefficient, not a stale CSV weight.
                _pitch(
                    101,
                    1,
                    pitch_type="SL",
                    description="hit_into_play",
                    event="single",
                    rv=0.3,
                    actual=0.897,
                    expected=0.4,
                    verified=0.882,
                ),
                # A field-out gets zero wOBA weight regardless of a stale source weight.
                _pitch(
                    101,
                    2,
                    pitch_type="SL",
                    description="hit_into_play",
                    event="field_out",
                    rv=-0.2,
                    actual=0.897,
                    expected=0.5,
                    verified=0.0,
                ),
                # Non-contact RV is unchanged regardless of season.
                _pitch(101, 3, pitch_type="SL", description="called_strike", rv=-0.05),
                # 2026 uses its own linear-weights scale.
                _pitch(
                    102,
                    1,
                    pitch_type="FF",
                    description="hit_into_play",
                    event="single",
                    rv=0.3,
                    actual=0.897,
                    expected=0.4,
                ),
                # Null xwOBA does NOT become 0 and does not count as paired.
                _pitch(
                    102,
                    2,
                    pitch_type="FF",
                    description="hit_into_play",
                    event="field_out",
                    rv=-0.2,
                    actual=0.0,
                    expected=None,
                ),
            ]
        )
        db.session.commit()

        slider = _snapshot(Pitch.pitch_type == "SL")
        fastball = _snapshot(Pitch.pitch_type == "FF")
        overall = _snapshot()

        slider_correction = (0.882 - 0.4 + 0.0 - 0.5) / WOBA_SCALES[2025]
        fastball_correction = (0.890 - 0.4) / WOBA_SCALES[2026]

        assert slider["xrv_scored_pitches"] == 3
        assert fastball["xrv_scored_pitches"] == 1
        assert fastball["xrv_missing_contact"] == 1
        assert fastball["xrv_imported_weight_mismatch"] == 1
        assert slider["xrv_paired_actual"] == pytest.approx(-0.05)
        assert fastball["xrv_paired_actual"] == pytest.approx(-0.3)
        assert slider["xrv_paired_expected"] == pytest.approx(-0.05 + slider_correction)
        assert fastball["xrv_paired_expected"] == pytest.approx(-0.3 + fastball_correction)

        assert overall["xrv_scored_pitches"] == 4
        assert overall["xrv_missing_contact"] == 1
        assert overall["xrv_paired_actual"] == pytest.approx(
            slider["xrv_paired_actual"] + fastball["xrv_paired_actual"]
        )
        assert overall["xrv_paired_expected"] == pytest.approx(
            slider["xrv_paired_expected"] + fastball["xrv_paired_expected"]
        )
        # Pitcher RV minus xRV = (expected contact wOBA - actual weight) / scale.
        assert (overall["xrv_paired_actual"] - overall["xrv_paired_expected"]) == pytest.approx(
            -(slider_correction + fastball_correction)
        )


def test_missing_season_scale_excludes_only_contact(app):
    with app.app_context():
        db.session.add(Player(mlb_id=801, player_name="Independent Audit"))
        db.session.add(
            Game(
                game_pk=99,
                season=2027,
                game_date=date(2027, 7, 1),
                home_team="BOS",
                away_team="NYY",
            )
        )
        db.session.flush()
        db.session.add_all(
            [
                _pitch(99, 1, pitch_type="FF", description="called_strike", rv=-0.1),
                _pitch(
                    99,
                    2,
                    pitch_type="FF",
                    description="hit_into_play",
                    event="single",
                    rv=0.2,
                    actual=0.890,
                    expected=0.4,
                ),
            ]
        )
        db.session.commit()

        scored = _snapshot()
        assert scored["xrv_scored_pitches"] == 1
        assert scored["xrv_unknown_scale"] == 1
        assert scored["xrv_missing_contact"] == 1
        assert scored["xrv_paired_actual"] == pytest.approx(0.1)
        assert scored["xrv_paired_expected"] == pytest.approx(0.1)
