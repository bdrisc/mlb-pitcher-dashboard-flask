"""Checks for fail-closed baseline and reference handling."""

from pathlib import Path

import pytest

from scripts import snapshot_integrity


def test_reviewed_reference_hashes_match_repository():
    assert snapshot_integrity.reference_hashes().items() >= snapshot_integrity.REFERENCES.items()


def test_text_digest_is_independent_of_line_endings(tmp_path: Path):
    path = tmp_path / "reference.json"
    path.write_bytes(b"a\r\nb\r\n")
    before = snapshot_integrity.file_digest(path)
    path.write_bytes(b"a\nb\n")
    assert snapshot_integrity.file_digest(path) == before


def test_wrong_audit_rejected_before_connection(tmp_path: Path):
    path = tmp_path / "audit.json"
    path.write_text('{"status": "PASS", "results": []}')
    with pytest.raises(ValueError, match="differs"):
        snapshot_integrity.validate_report(path)


def test_drift_detection_fails_on_changed_or_missing_sections():
    before = {"local": {"rows": 1}, "public": {"rows": 2}, "schema": 1}
    assert snapshot_integrity.differences(before, before.copy()) == []
    assert snapshot_integrity.differences(before, {"local": {"rows": 2}, "schema": 1}) == [
        "local",
        "public",
    ]
