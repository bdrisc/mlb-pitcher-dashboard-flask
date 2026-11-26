"""A synthetic release is never a production authorization."""

import json

import pytest

from scripts.apply_reviewed_future_leaderboards import expected_approval, validate_approval
from scripts.rehearse_future_release import BLOCKERS, future_plan, verify_manifest
from scripts.rehearse_snapshot_release import ReleaseError, evidence, sha


def fixture_manifest(path):
    historical = {
        "status": "PASS",
        "index_differences": [],
        "results": [
            {
                "pitcher_id": i,
                "endpoint": "profile",
                "scope": "full",
                "status": "PASS",
                "different_fields": 0,
            }
            for i in range(660)
        ],
    }
    future = {
        "status": "PASS",
        "results": [
            {"scope": scope, "endpoint": endpoint, "pitches": n, "http": 200 if n else 404}
            for scope, _, n in future_plan()
            for endpoint in ("profile", "charts")
        ],
    }
    (path / "historical_parity.json").write_text(json.dumps(historical), encoding="utf-8")
    (path / "future_parity.json").write_text(json.dumps(future), encoding="utf-8")
    (path / "synthetic_public_candidate.dump").write_bytes(b"synthetic archive")
    report = {
        "schema": 1,
        "status": "PACKAGE_C_SYNTHETIC_PASS_NOT_PUBLISHED",
        "synthetic": True,
        "season": 2027,
        "production_write_allowed": False,
        "publication_blockers": BLOCKERS,
        "candidate_database": "mlb_release_candidate_0123456789ab",
        "restored_database": "mlb_release_candidate_abcdef012345",
        "candidate_fingerprint": {"example": "hash"},
        "restored_fingerprint": {"example": "hash"},
        "historical_cases": 660,
        "future_cases": len(future["results"]),
        "artifacts": {p.name: evidence(p) for p in path.iterdir()},
    }
    manifest = path / "release_manifest.json"
    manifest.write_text(json.dumps(report), encoding="utf-8")
    return manifest, report


def test_passed_manifest_is_not_publication_approval(tmp_path):
    manifest, report = fixture_manifest(tmp_path)
    assert verify_manifest(tmp_path, sha(manifest)) == report
    assert not report["production_write_allowed"]


@pytest.mark.parametrize("field", ["synthetic", "production_write_allowed", "restored_fingerprint"])
def test_manifest_rejects_changed_release_state(tmp_path, field):
    manifest, report = fixture_manifest(tmp_path)
    report[field] = not report[field]
    manifest.write_text(json.dumps(report), encoding="utf-8")
    with pytest.raises(ReleaseError, match="Invalid synthetic release manifest"):
        verify_manifest(tmp_path, sha(manifest))


def test_manifest_rejects_archive_tampering(tmp_path):
    manifest, _ = fixture_manifest(tmp_path)
    (tmp_path / "synthetic_public_candidate.dump").write_bytes(b"changed")
    with pytest.raises(ReleaseError, match="Release artifact changed"):
        verify_manifest(tmp_path, sha(manifest))


def test_manifest_rejects_wrong_future_cases_even_with_updated_digest(tmp_path):
    manifest, report = fixture_manifest(tmp_path)
    path = tmp_path / "future_parity.json"
    future = json.loads(path.read_bytes())
    future["results"][0]["pitches"] = 5
    path.write_text(json.dumps(future), encoding="utf-8")
    report["artifacts"][path.name] = evidence(path)
    manifest.write_text(json.dumps(report), encoding="utf-8")
    with pytest.raises(ReleaseError, match="Future comparison evidence failed"):
        verify_manifest(tmp_path, sha(manifest))


def test_real_approval_binds_exact_review():
    package = {
        "synthetic": False,
        "status": "PACKAGE_A_EVIDENCE_REVIEW_REQUIRED",
        "production_write_allowed": False,
        "season": 2027,
        "leaderboard_coverage": {"missing_values": [[1, "xera"]]},
        "game_results": {"2": {"physical_pitches": 6}},
        "crosswalk_report_sha256": "c" * 64,
    }
    approval = expected_approval(2027, "a" * 64, "b" * 64, package)
    approval["review_notes"] = "Reviewed exact fixture coverage."
    validate_approval(approval, 2027, "a" * 64, "b" * 64, package)
    approval["production_write_allowed"] = True
    with pytest.raises(ReleaseError, match="operator approval"):
        validate_approval(approval, 2027, "a" * 64, "b" * 64, package)
    package["synthetic"] = True
    with pytest.raises(ReleaseError, match="Not real"):
        expected_approval(2027, "a" * 64, "b" * 64, package)
