"""Official barrel counting, coverage, ingestion and safe field-only backfills."""

import pandas as pd
import pytest
from sqlalchemy import func, select

from app.extensions import db
from app.models import Pitch
from app.services.barrel_refresh import refresh_barrels, source_records
from app.services.statcast_ingestion import IngestionError, clean_statcast, ingest_statcast_file
from tests.test_pitcher_profile import _pitch
from tests.test_pitcher_profile import profile_client as profile_client_fixture
from tests.test_statcast_ingestion import statcast_rows

profile_client = profile_client_fixture
URL = "/api/v1/pitchers/100/profile"


@pytest.fixture
def barrel_client(app, profile_client):
    with app.app_context():
        db.session.query(Pitch).delete()
        for n, (code, category, checked, description) in enumerate(
            [
                ("FF", 6, True, "hit_into_play"),
                ("FF", 2, True, "hit_into_play"),
                ("FF", None, True, "hit_into_play"),
                ("SL", 6, True, "hit_into_play"),
                ("SL", 6, True, "foul"),
                ("SL", None, None, "swinging_strike"),
            ],
            1,
        ):
            db.session.add(
                _pitch(
                    pitch_id=f"1001_{n}_1",
                    game_pk=1001,
                    batter_id=200,
                    at_bat_number=n,
                    pitch_number=1,
                    balls=0,
                    strikes=2,
                    pitch_type=code,
                    pitch_name=code,
                    batter_side="R",
                    inning_half="Top",
                    launch_speed_angle=category,
                    barrel_checked=checked,
                    description=description,
                    events="field_out" if description == "hit_into_play" else None,
                    velocity=95,
                    estimated_woba=0.2,
                )
            )
        db.session.commit()
    return profile_client


def test_barrels_pool_all_bbe_not_pitches_or_type_rates(barrel_client):
    data = barrel_client.get(URL).json
    metrics = data["overall"]
    assert metrics["barrel_pct"] == 50.0
    assert metrics["barrel_count"] == 2
    assert metrics["barrel_bbe_count"] == metrics["barrel_checked_bbe_count"] == 4
    assert metrics["barrel_classified_bbe_count"] == 3
    assert metrics["barrel_coverage_pct"] == 75.0
    arsenal = {row["pitch_type"]: row for row in data["arsenal"]}
    assert arsenal["FF"]["barrel_pct"] == 33.3
    assert arsenal["SL"]["barrel_pct"] == 100.0
    assert data["platoon_splits"][0]["barrel_pct"] == 50.0
    assert metrics["barrel_pct"] != (33.3 + 100) / 2


def test_barrel_filters_zero_and_unprocessed_coverage(app, barrel_client):
    assert (
        barrel_client.get(URL + "?pitch_type=FF&strikes=2&batter_side=R").json["overall"][
            "barrel_pct"
        ]
        == 33.3
    )
    with app.app_context():
        db.session.get(Pitch, "1001_1_1").barrel_checked = None
        db.session.commit()
    assert barrel_client.get(URL).json["overall"]["barrel_pct"] is None
    assert barrel_client.get(URL + "?pitch_type=SL").json["overall"]["barrel_pct"] == 100.0
    with app.app_context():
        db.session.get(Pitch, "1001_1_1").barrel_checked = True
        for pitch in db.session.scalars(select(Pitch)):
            if pitch.launch_speed_angle == 6:
                pitch.launch_speed_angle = 2
        db.session.commit()
    assert barrel_client.get(URL).json["overall"]["barrel_pct"] == 0.0
    with app.app_context():
        for pitch in db.session.scalars(select(Pitch)):
            pitch.description = "ball"
        db.session.commit()
    assert barrel_client.get(URL).json["overall"]["barrel_pct"] is None


def source_frame(owner=100):
    return pd.DataFrame(
        [
            dict(
                game_pk=1001,
                at_bat_number=n,
                pitch_number=1,
                pitcher=owner,
                game_year=2026,
                description="hit_into_play",
                launch_speed_angle=value,
            )
            for n, value in [(1, 6), (2, 2), (3, None), (4, 6)]
        ]
    )


def mark_pending(app):
    with app.app_context():
        for pitch in db.session.scalars(select(Pitch)):
            pitch.launch_speed_angle = None
            pitch.barrel_checked = None
        db.session.commit()


def test_csv_backfill_only_updates_existing_barrel_fields(
    app, barrel_client, tmp_path, monkeypatch
):
    mark_pending(app)
    frame = source_frame()
    extra = frame.iloc[[0]].copy()
    extra["game_pk"] = 9999
    path = tmp_path / "source.csv.gz"
    pd.concat([frame, extra]).to_csv(path, index=False)
    monkeypatch.setattr(
        "app.services.barrel_refresh.fetch_barrel_values",
        lambda _: pytest.fail("Complete CSV must not download"),
    )
    before = barrel_client.get(URL).json
    with app.app_context():
        count = db.session.scalar(select(func.count(Pitch.pitch_id)))
        result = refresh_barrels(source_paths=[path], season=2026)
        assert result["updated_bbe"] == 4 and result["remaining_bbe"] == 0
        assert db.session.scalar(select(func.count(Pitch.pitch_id))) == count
        assert db.session.get(Pitch, "1001_3_1").barrel_checked is True
        assert db.session.get(Pitch, "1001_3_1").launch_speed_angle is None
        assert db.session.get(Pitch, "1001_5_1").barrel_checked is None
        assert refresh_barrels(source_paths=[path])["updated_bbe"] == 0
    after = barrel_client.get(URL).json
    assert after["overall"]["barrel_pct"] == 50.0
    for key in before["overall"]:
        if not key.startswith("barrel_"):
            assert before["overall"][key] == after["overall"][key]
    assert before["sample"] == after["sample"]


def test_network_backfill_checks_completeness_and_owner(app, barrel_client, monkeypatch):
    mark_pending(app)
    good = source_records(source_frame())
    for records in [{}, source_records(source_frame(owner=999)), good]:
        monkeypatch.setattr("app.services.barrel_refresh.fetch_barrel_values", lambda _: records)
        with app.app_context():
            result = refresh_barrels(workers=1)
        if records is good:
            assert result["remaining_bbe"] == 0 and not result["failed"]
        else:
            assert result["remaining_bbe"] == 4 and result["failed"]
            assert barrel_client.get(URL).json["overall"]["barrel_pct"] is None


@pytest.mark.parametrize("value", [0, 7, 6.1, "broken"])
def test_invalid_source_classifications_rejected(value):
    frame = source_frame()
    frame["launch_speed_angle"] = value
    with pytest.raises(ValueError):
        source_records(frame)
    raw = statcast_rows()
    raw["launch_speed_angle"] = value
    with pytest.raises(IngestionError):
        clean_statcast(raw)


def test_ingestion_retains_classification_when_sparse_source_reimported(app, tmp_path):
    raw = statcast_rows()
    raw["launch_speed_angle"] = None
    raw.loc[raw.description.eq("hit_into_play"), "launch_speed_angle"] = 6
    path = tmp_path / "raw.csv"
    raw.to_csv(path, index=False)
    with app.app_context():
        ingest_statcast_file(path)
        pitches = db.session.scalars(
            select(Pitch).where(Pitch.description == "hit_into_play")
        ).all()
        assert pitches and all(p.launch_speed_angle == 6 and p.barrel_checked for p in pitches)
        ids = [p.pitch_id for p in pitches]
        raw.drop(columns="launch_speed_angle").to_csv(path, index=False)
        ingest_statcast_file(path)
        db.session.expire_all()
        assert all(db.session.get(Pitch, key).launch_speed_angle == 6 for key in ids)
        assert all(db.session.get(Pitch, key).barrel_checked for key in ids)


def test_barrel_display_and_cli(app, barrel_client, tmp_path):
    html = barrel_client.get("/savant-card").get_data(as_text=True)
    assert "Barrel% Allowed" in html
    assert html.index('data-metric="hard_hit_pct"') < html.index('data-metric="barrel_pct"')
    assert html.index('data-metric="barrel_pct"') < html.index('data-metric="stuff_plus"')
    mark_pending(app)
    path = tmp_path / "source.csv"
    source_frame().to_csv(path, index=False)
    result = app.test_cli_runner().invoke(
        args=["statcast", "backfill-barrels", "--season", "2026", "--csv-path", str(path)]
    )
    assert result.exit_code == 0, result.output
    assert barrel_client.get(URL).json["overall"]["barrel_pct"] == 50.0


def test_all_unclassified_bbe_are_not_displayed_as_zero(app, barrel_client):
    with app.app_context():
        for pitch in db.session.scalars(select(Pitch)):
            pitch.launch_speed_angle = None
        db.session.commit()
    metrics = barrel_client.get(URL).json["overall"]
    assert metrics["barrel_bbe_count"] == metrics["barrel_checked_bbe_count"] == 4
    assert metrics["barrel_classified_bbe_count"] == 0
    assert metrics["barrel_pct"] is None


def test_csv_ownership_failure_rolls_back_whole_file(app, barrel_client, tmp_path):
    mark_pending(app)
    frame = source_frame()
    frame.loc[2, "pitcher"] = 999
    path = tmp_path / "wrong_owner.csv"
    frame.to_csv(path, index=False)
    with app.app_context():
        with pytest.raises(ValueError, match="ownership"):
            refresh_barrels(source_paths=[path])
        assert (
            db.session.scalar(
                select(func.count(Pitch.pitch_id)).where(Pitch.barrel_checked.is_(True))
            )
            == 0
        )
    assert barrel_client.get(URL).json["overall"]["barrel_pct"] is None
