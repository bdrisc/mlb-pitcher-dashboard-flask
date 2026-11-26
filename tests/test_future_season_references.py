"""Future metrics must not reuse historical constants or cohort league baselines."""

import json
from datetime import date

import pytest
from sqlalchemy import select

from app.extensions import db
from app.models import Game, Pitch, Player
from app.services import future_season_references as future
from app.services.expected_run_value import expected_run_value_columns
from app.services.filters import PitchFilters
from app.services.location_performance import build_location_performance
from app.services.location_reference import FIELDS, future_league_bins
from app.services.movement_reference import movement_vs_average
from app.services.pitch_roles import ROLE_FIELDS, build_pitch_roles, role_values
from scripts.build_future_season_references import parse_coefficients, write_location

WEIGHTS = [1.2, 0.8, 1.2, 1.6, 2.0]


def entry():
    return {
        "season": 2027,
        "synthetic": False,
        "start": "2027-04-01",
        "through": "2027-04-02",
        "scope": "complete_mlb_regular_season_to_date",
        "coverage": [1, 6, 6, 2],
        "package_a_sha256": "a" * 64,
        "candidate_fingerprint_sha256": "b" * 64,
        "coefficients": {
            "values": WEIGHTS,
            "source": "https://www.fangraphs.com/tools/guts?type=cn",
            "source_sha256": "c" * 64,
            "as_of": "2027-04-02",
        },
        "artifacts": {},
    }


@pytest.fixture
def registry(monkeypatch, tmp_path):
    monkeypatch.setattr(future, "DATA", tmp_path)
    path = tmp_path / "registry.json"
    monkeypatch.setattr(future, "REGISTRY", path)
    return path


def install(path, value):
    path.write_text(json.dumps({"schema": 1, "seasons": {"2027": value}}), encoding="utf-8")
    future._registry.cache_clear()


@pytest.mark.parametrize("failure", ["synthetic", "date", "coverage", "coefficients", "scope"])
def test_registry_rejects_invalid_entry(registry, failure):
    data = entry()
    if failure == "synthetic":
        data["synthetic"] = True
    elif failure == "date":
        data["through"] = "2026-04-02"
    elif failure == "coverage":
        data["coverage"][2] = 5
    elif failure == "coefficients":
        data["coefficients"]["values"] = [1.2, 0.8, 1.2, 1.6, float("nan")]
    else:
        data["scope"] = "public_cohort"
    install(registry, data)
    assert future.approved_weights() == {}


def test_coefficients_exact_season():
    raw = b"Season,wOBAScale,w1B,w2B,w3B,wHR\n2027,1.2,.8,1.2,1.6,2\n"
    assert parse_coefficients(raw, 2027) == WEIGHTS
    with pytest.raises(ValueError, match="matching season"):
        parse_coefficients(raw, 2028)
    with pytest.raises(ValueError, match="matching season"):
        parse_coefficients(raw + raw.splitlines(keepends=True)[1], 2027)


def test_future_location_checksum_and_date_scope(registry):
    data = entry()
    path = registry.parent / "league_location_2027.json.gz"
    payload = {
        "version": 1,
        "season": 2027,
        "fields": list(FIELDS),
        "physical_coverage": data["coverage"],
        "start": data["start"],
        "through": data["through"],
        "game_types": {"R": 6},
        "rows": [["2027-04-01", 0, 0, "home", "R", "FF", "R", 1, 1, 1, 1, ".5", 1, "100", 1]],
    }
    write_location(path, payload)
    data["artifacts"]["location"] = {"file": path.name, "sha256": future.digest(path)}
    install(registry, data)
    rows, through = future_league_bins(PitchFilters(season=2027), "R")
    assert rows[0]["xwoba_sum"] == 0.5
    assert through == "2027-04-02"
    assert future_league_bins(PitchFilters(season=2027, date_to=date(2027, 4, 3)), "R") is None
    path.write_bytes(b"tampered")
    assert future_league_bins(PitchFilters(season=2027), "R") is None


def test_unapproved_future_reference_never_reads_unpinned_files(registry):
    install(registry, entry())
    path = registry.parent / "league_movement_2027.csv.gz"
    path.write_bytes(b"unapproved")
    assert future.artifact(2027, "movement") is None
    result = movement_vs_average(
        season=2027,
        pitch_type="FF",
        throwing_hand="R",
        arm_angle=40,
        horizontal_break=-8,
        vertical_break=16,
    )
    assert result["hb_vs_avg"] is None
    assert result["ivb_vs_avg"] is None


def test_xrv_future_without_and_with_approved_weights(app, registry):
    with app.app_context():
        db.session.add(Player(mlb_id=101, player_name="Future Fixture"))
        db.session.add(
            Game(
                game_pk=12,
                season=2027,
                game_date=date(2027, 4, 1),
                home_team="BOS",
                away_team="NYY",
                game_type="R",
            )
        )
        db.session.flush()
        for number, description, event, rv, xwoba in (
            (1, "called_strike", None, -0.1, None),
            (2, "hit_into_play", "home_run", 1.0, 0.5),
        ):
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
                    estimated_woba=xwoba,
                )
            )
        db.session.commit()

        def metrics():
            stmt = (
                select(*expected_run_value_columns())
                .select_from(Pitch)
                .join(Game, Game.game_pk == Pitch.game_pk)
            )
            return db.session.execute(stmt).mappings().one()

        unavailable = metrics()
        assert unavailable["xrv_scored_pitches"] == 0
        assert unavailable["xrv_paired_expected"] is None
        db.session.add(
            Game(
                game_pk=13,
                season=2026,
                game_date=date(2026, 4, 1),
                home_team="BOS",
                away_team="NYY",
                game_type="R",
            )
        )
        db.session.flush()
        db.session.add(
            Pitch(
                pitch_id="13_1_1",
                game_pk=13,
                pitcher_id=101,
                batter_id=101,
                at_bat_number=1,
                pitch_number=1,
                pitch_type="FF",
                balls=0,
                strikes=0,
                description="called_strike",
                delta_run_expectancy=-0.2,
            )
        )
        db.session.commit()
        assert metrics()["xrv_paired_expected"] is None
        install(registry, entry())
        ready = metrics()
        assert ready["xrv_scored_pitches"] == 3
        assert ready["xrv_paired_expected"] == pytest.approx(-0.7 + (2 - 0.5) / 1.2)
        location = build_location_performance(101, PitchFilters(season=2027), "R")
        assert location["league_bins"] == []
        assert location["reference_scope"] == "Approved full-league reference unavailable"


def test_roles_require_approved_reference(registry):
    data = entry()
    data["coverage"] = [300, 200000, 200000, 600]
    path = registry.parent / "league_pitch_roles_2027.json"
    payload = {
        "version": 1,
        "season": 2027,
        "pitchers": 300,
        "physical_pitches": 200000,
        "games": 600,
        "through": data["through"],
        "distributions": {
            "FF|R|ALL|0-0|whiff_pct": [20] * 20,
        },
    }
    path.write_text(json.dumps(payload), encoding="utf-8")
    stats = dict.fromkeys(ROLE_FIELDS, 0)
    stats.update(physical_pitch_count=100, role_regular_pitches=100, swings=80, whiffs=40)
    arsenal = [{"pitch_type": "FF", "role_values": role_values(stats)}]
    filters = PitchFilters(season=2027, balls=0, strikes=0)
    assert not build_pitch_roles(arsenal, filters, "R")["reference_available"]
    data["artifacts"]["roles"] = {"file": path.name, "sha256": future.digest(path)}
    install(registry, data)
    result = build_pitch_roles(arsenal, filters, "R")
    assert result["reference_available"]
    assert result["rows"][1]["cells"][0]["percentile"] == 100
    path.write_text("tampered", encoding="utf-8")
    assert not build_pitch_roles(arsenal, filters, "R")["reference_available"]
