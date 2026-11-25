"""Tests for guarded future-season ingestion and source staging."""

import json

import pytest

from app.extensions import db
from app.models import Pitch, Player
from app.services.statcast_ingestion import IngestionError, ingest_statcast_file
from scripts.rehearse_snapshot_release import ReleaseError
from scripts.stage_future_ingestion import synthetic_sources, verified_sources
from tests.test_statcast_ingestion import statcast_rows, write_statcast_csv


def test_synthetic_sources_are_bound_to_manifest(tmp_path):
    paths, schedule, manifest, digest = synthetic_sources(tmp_path)
    reviewed, games, copies = verified_sources(
        paths, schedule, manifest, digest, 2027, tmp_path / "copied"
    )
    assert reviewed["rows"] == 6
    assert len(games) == 2
    assert len(copies) == 2
    assert json.loads(manifest.read_bytes()) == reviewed
    with paths[0].open("ab") as out:
        out.write(b"\n")
    with pytest.raises(ReleaseError):
        verified_sources(paths, schedule, manifest, digest, 2027, tmp_path / "changed")


def test_future_load_preserves_existing_players_and_rejects_overlaps(app, tmp_path):
    historical = write_statcast_csv(tmp_path, statcast_rows())
    with app.app_context():
        ingest_statcast_file(historical)
        original = db.session.get(Player, 800048)
        before = (original.player_name, original.throws)
        future = statcast_rows()
        future["game_date"] = "2027-04-01"
        future["game_pk"] = 824567
        future["player_name"] = "Changed, Name"
        future["p_throws"] = "R"
        future_path = tmp_path / "future.csv"
        future.to_csv(future_path, index=False)
        result = ingest_statcast_file(
            future_path, frozen_player_ids=frozenset({800048}), insert_only_season=2027
        )
        assert result.inserted_rows == 3
        assert result.updated_rows == 0
        player = db.session.get(Player, 800048)
        assert (player.player_name, player.throws) == before
        assert db.session.get(Pitch, "824567_8_1").pitcher_throws == "R"
        with pytest.raises(IngestionError):
            ingest_statcast_file(future_path, insert_only_season=2027)
        with pytest.raises(IngestionError):
            ingest_statcast_file(historical, insert_only_season=2027)
        assert db.session.query(Pitch).count() == 6
