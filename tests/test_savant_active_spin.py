"""Official spin-based Active Spin %: independently published, not pitch-inferred."""

from datetime import datetime
from urllib.parse import parse_qs, urlparse

import pandas as pd
import pytest
from sqlalchemy import func, select

from app.extensions import db
from app.models import Pitch, Player, SavantActiveSpin
from app.services.published_pitching_fetch import (
    fetch_savant_active_spin,
    normalize_savant_active_spin_csv,
)
from app.services.savant_active_spin import (
    SAVANT_SPIN_FIELDS,
    import_savant_active_spin,
    published_active_spin,
)


def active_frame(player_id=100):
    row = {
        "entity_id": player_id,
        "entity_name": "Sample Pitcher",
        "pitch_hand": "R",
        **{field: None for field in SAVANT_SPIN_FIELDS},
    }
    row["active_spin_fourseam"] = 96.2
    row["active_spin_slider"] = 24.5
    return pd.DataFrame([row])


def test_source_is_explicitly_spin_based_not_observed(monkeypatch):
    captured = []

    def fetch(url, **kwargs):
        captured.append((url, kwargs))
        return active_frame().to_csv(index=False).encode()

    monkeypatch.setattr("app.services.published_pitching_fetch._download", fetch)
    frame = fetch_savant_active_spin(2026)
    assert frame.iloc[0]["active_spin_fourseam"] == 96.2
    url, kwargs = captured[0]
    assert urlparse(url).path.endswith("/leaderboard/active-spin")
    assert parse_qs(urlparse(url).query)["year"] == ["2026_spin-based"]
    assert parse_qs(urlparse(url).query)["csv"] == ["true"]
    assert parse_qs(urlparse(url).query)["min"] == ["1"]
    assert kwargs["accept"] == "text/csv"


def test_ambiguous_or_invalid_source_does_not_pass_validation():
    ok = active_frame().to_csv(index=False).encode()
    assert normalize_savant_active_spin_csv(ok, 2026).iloc[0]["entity_id"] == 100
    for bad in (
        b"<!DOCTYPE html><body>Forbidden</body>",
        active_frame().drop(columns=["active_spin_slider"]).to_csv(index=False).encode(),
        pd.concat([active_frame(), active_frame()], ignore_index=True).to_csv(index=False).encode(),
        active_frame().assign(year=2025).to_csv(index=False).encode(),
    ):
        with pytest.raises((ValueError, pd.errors.ParserError)):
            normalize_savant_active_spin_csv(bad, 2026)


def test_import_is_atomic_and_does_not_modify_pitch_data(app):
    with app.app_context():
        pitches_before = db.session.scalar(select(func.count()).select_from(Pitch))
        players_before = db.session.scalar(select(func.count()).select_from(Player))
        result = import_savant_active_spin(active_frame(), 2026)
        assert result["pitch_rows"] == 2
        values = published_active_spin(100, 2026)
        assert values == {"FF": 96.2, "SL": 24.5}
        assert published_active_spin(100, 2025) == {}
        saved = db.session.get(SavantActiveSpin, (100, 2026, "FF"))
        assert saved.active_spin_pct == 96.2
        assert isinstance(saved.updated_at, datetime)
        assert db.session.scalar(select(func.count()).select_from(Pitch)) == pitches_before
        assert db.session.scalar(select(func.count()).select_from(Player)) == players_before

        invalid = active_frame()
        invalid["active_spin_fourseam"] = 101.0
        with pytest.raises(ValueError, match="Invalid active_spin_fourseam"):
            import_savant_active_spin(invalid, 2026)
        assert published_active_spin(100, 2026) == values

        incoming = active_frame()
        incoming["active_spin_fourseam"] = 94.1
        incoming["active_spin_slider"] = None
        import_savant_active_spin(incoming, 2026)
        assert published_active_spin(100, 2026) == {"FF": 94.1, "SL": 24.5}
        assert saved.active_spin_pct == 94.1


def test_import_rejects_missing_pitch_columns_and_invalid_ids(app):
    with app.app_context():
        for frame in (
            active_frame().drop(columns=["active_spin_fourseam"]),
            active_frame(player_id=0),
            active_frame(player_id=100.25),
            active_frame().assign(active_spin_fourseam="NaN!"),
            active_frame().assign(active_spin_slider=float("inf")),
            active_frame().assign(year=2025),
        ):
            with pytest.raises(ValueError):
                import_savant_active_spin(frame, 2026)
        assert db.session.scalar(select(func.count()).select_from(SavantActiveSpin)) == 0


def test_import_and_sync_cli_use_same_source_without_estimating(app, tmp_path, monkeypatch):
    source = tmp_path / "active_spin.csv"
    active_frame().to_csv(source, index=False)
    cli = app.test_cli_runner()

    imported = cli.invoke(args=["published", "import-active-spin", str(source), "--season", "2026"])
    assert imported.exit_code == 0, imported.output
    assert "pitch_rows" in imported.output

    def mock_acquire(provider, season, side, destination, timeout):
        assert (provider, season, side) == ("savant-active-spin", 2026, "ALL")
        return active_frame().assign(active_spin_fourseam=93.0)

    monkeypatch.setattr("app.commands.published._acquire", mock_acquire)
    refreshed = cli.invoke(args=["published", "sync-active-spin", "--season", "2026"])
    assert refreshed.exit_code == 0, refreshed.output
    with app.app_context():
        assert published_active_spin(100, 2026)["FF"] == 93.0
