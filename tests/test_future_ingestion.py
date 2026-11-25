"""Tests for guarded future-season ingestion and source staging."""

import json

import pytest

from scripts.rehearse_snapshot_release import ReleaseError
from scripts.stage_future_ingestion import synthetic_sources, verified_sources


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
