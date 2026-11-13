"""Publisher-source parity and safe import tests; no internet needed."""

import json
from urllib.parse import parse_qs, urlparse

import pandas as pd
import pytest
from sqlalchemy import func, select

from app.extensions import db
from app.models import Player, PublishedPitchingMetric
from app.services.published_pitching import (
    import_fangraphs_published,
    import_savant_xera,
    published_references,
)
from app.services.published_pitching_fetch import (
    fetch_fangraphs,
    normalize_fangraphs,
    normalize_savant_csv,
    validate_handedness_split,
)


def fg_frame(id_number=100, fip=3.40, xfip=3.15, siera=3.21):
    return pd.DataFrame(
        [
            {
                "IDfg": 44,
                "mlb_id": id_number,
                "Season": 2026,
                "FIP": fip,
                "xFIP": xfip,
                "SIERA": siera,
            }
        ]
    )


def savant_frame(id_number=100, xera=2.88):
    return pd.DataFrame([{"player_id": id_number, "year": 2026, "xera": xera}])


def test_provider_values_are_stored_verbatim_without_statcast_mutation(app):
    with app.app_context():
        players_before = db.session.scalar(select(func.count()).select_from(Player))
        import_fangraphs_published(fg_frame(), 2026, "ALL")
        import_fangraphs_published(fg_frame(fip=4.01), 2026, "R")
        import_savant_xera(savant_frame(xera=2.88), 2026)
        records = published_references(100, 2026)
        assert records["ALL"]["fip"] == 3.40
        assert records["ALL"]["xfip"] == 3.15
        assert records["ALL"]["siera"] == 3.21
        assert records["ALL"]["xera"] == 2.88
        assert records["R"]["fip"] == 4.01
        assert records["R"]["xera"] is None
        assert records["L"]["fip"] is None
        assert records["ALL"]["reference_fangraphs_updated"] is not None
        assert records["ALL"]["reference_savant_updated"] is not None
        assert db.session.scalar(select(func.count()).select_from(Player)) == players_before
        assert published_references(100, 2025)["ALL"]["fip"] is None


def test_savant_reimport_preserves_fangraphs_and_fangraphs_preserves_savant(app):
    with app.app_context():
        import_fangraphs_published(fg_frame(), 2026)
        import_savant_xera(savant_frame(), 2026)
        import_fangraphs_published(fg_frame(fip=3.66), 2026)
        import_savant_xera(savant_frame(xera=3.02), 2026)
        record = db.session.get(PublishedPitchingMetric, (100, 2026, "ALL"))
        assert (record.fip, record.xfip, record.siera, record.xera) == (3.66, 3.15, 3.21, 3.02)


def test_upstream_invalid_or_duplicate_data_does_not_replace_previous_stats(app):
    with app.app_context():
        import_fangraphs_published(fg_frame(), 2026)
        import_savant_xera(savant_frame(), 2026)
        for invalid in (
            fg_frame(fip="invalid"),
            fg_frame().drop(columns="SIERA"),
            fg_frame().assign(Season=2025),
            pd.concat([fg_frame(), fg_frame()], ignore_index=True),
        ):
            with pytest.raises(ValueError):
                import_fangraphs_published(invalid, 2026)
        for invalid in (
            savant_frame().assign(year=2025),
            savant_frame().drop(columns="xera"),
            pd.concat([savant_frame(), savant_frame()], ignore_index=True),
        ):
            with pytest.raises(ValueError):
                import_savant_xera(invalid, 2026)
        record = db.session.get(PublishedPitchingMetric, (100, 2026, "ALL"))
        assert record.fip == 3.40
        assert record.xera == 2.88


def test_publisher_rows_need_mlb_id_not_name_guessing(app):
    with app.app_context():
        source = fg_frame().drop(columns="mlb_id")
        with pytest.raises(ValueError):
            import_fangraphs_published(source.drop(columns="IDfg"), 2026)
        # The same name alone cannot create a match; no fuzzy joins.
        assert db.session.scalar(select(func.count()).select_from(PublishedPitchingMetric)) == 0


def test_fangraphs_acquisition_requires_complete_schema_and_correct_season():
    payload = {
        "data": [
            {
                "playerid": 44,
                "xMLBAMID": 100,
                "Season": 2026,
                "FIP": 3.66,
                "xFIP": 3.22,
                "SIERA": 3.10,
            }
        ],
        "totalCount": 1,
    }
    assert normalize_fangraphs(payload, 2026).iloc[0]["xFIP"] == 3.22
    with pytest.raises(ValueError):
        normalize_fangraphs({**payload, "totalCount": 2}, 2026)
    with pytest.raises(ValueError):
        normalize_fangraphs({**payload, "data": [{**payload["data"][0], "Season": 2025}]}, 2026)
    with pytest.raises(ValueError):
        normalize_fangraphs({**payload, "data": []}, 2026)


def test_fangraphs_split_download_passes_batter_hand_and_checks_response(monkeypatch):
    calls = []

    def stub(url, **kwargs):
        calls.append((parse_qs(urlparse(url).query), kwargs))
        return json.dumps(
            {
                "totalCount": 1,
                "data": [
                    {
                        "playerid": 44,
                        "xMLBAMID": 100,
                        "Season": 2026,
                        "FIP": 3.01,
                        "xFIP": 2.88,
                        "SIERA": 3.10,
                    }
                ],
            }
        ).encode()

    monkeypatch.setattr("app.services.published_pitching_fetch._download", stub)
    assert fetch_fangraphs(2026, "R").iloc[0]["FIP"] == 3.01
    assert calls[0][0]["hand"] == ["R"]
    assert calls[0][0]["type"] == ["8"]
    assert calls[0][0]["qual"] == ["0"]


def test_split_detector_rejects_falsely_labeled_full_season_totals():
    full = pd.DataFrame(
        [{"mlb_id": i, "FIP": 3.5, "xFIP": 3.6, "SIERA": 3.7} for i in range(100, 114)]
    )
    with pytest.raises(ValueError, match="ignore handedness"):
        validate_handedness_split(full, full)
    distinct = full.copy()
    distinct["FIP"] += 0.2
    validate_handedness_split(distinct, full)


def test_savant_csv_requires_official_xera_and_season():
    valid = savant_frame().to_csv(index=False).encode()
    assert normalize_savant_csv(valid, 2026).iloc[0]["xera"] == 2.88
    with pytest.raises(ValueError):
        normalize_savant_csv(b"<html>not a CSV</html>", 2026)
    with pytest.raises(ValueError):
        wrong_season = savant_frame(xera=2.88).assign(year=2025)
        normalize_savant_csv(wrong_season.to_csv(index=False).encode(), 2026)


def test_manual_source_import_commands_preserve_player_pool(app, tmp_path):
    fg_csv = tmp_path / "fg.csv"
    savant_csv = tmp_path / "savant.csv"
    fg_frame().to_csv(fg_csv, index=False)
    savant_frame().to_csv(savant_csv, index=False)
    runner = app.test_cli_runner()
    assert (
        runner.invoke(
            args=["published", "import-fangraphs", str(fg_csv), "--season", "2026"]
        ).exit_code
        == 0
    )
    assert (
        runner.invoke(
            args=["published", "import-savant", str(savant_csv), "--season", "2026"]
        ).exit_code
        == 0
    )
    with app.app_context():
        assert db.session.scalar(select(func.count()).select_from(Player)) == 0
        assert published_references(100, 2026)["ALL"]["xera"] == 2.88
