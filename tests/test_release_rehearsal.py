"""Test the offline release safeguards without touching a database."""

import csv

import pytest

from scripts.audit_future_statcast_sources import REQUIRED, scan
from scripts.rehearse_snapshot_release import ReleaseError, compare, recovery_url


def test_comparison_distinguishes_missing_null_and_bool():
    assert list(compare({"a": None}, {})) == ["a"]
    assert list(compare(True, 1)) == [""]
    assert list(compare([1, 2], [2, 1])) == ["[0]", "[1]"]
    assert list(compare({"a": 1.0, "updated_at": "x"}, {"a": 1.00000001})) == []


def test_only_isolated_loopback_database_names_allowed():
    original = "postgresql+psycopg://u:p@localhost:5432/original"
    target = "mlb_release_candidate_123456789abc"
    assert recovery_url(original, target).database == target
    with pytest.raises(ReleaseError):
        recovery_url(original, "original")
    with pytest.raises(ReleaseError):
        recovery_url(original.replace("localhost", "example.com"), target)
    with pytest.raises(ReleaseError):
        recovery_url(original + "?host=example.com", target)


def fixture_csv(path, year=2027):
    with path.open("w", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=sorted(REQUIRED))
        writer.writeheader()
        writer.writerow(
            {
                "game_date": f"{year}-04-01",
                "game_pk": 123,
                "at_bat_number": 1,
                "pitch_number": 1,
                "pitch_type": "FF",
                "player_name": "Pitcher",
                "pitcher": 10,
                "batter": 11,
                "stand": "R",
                "p_throws": "R",
                "balls": 0,
                "strikes": 0,
                "description": "called_strike",
                "type": "S",
                "home_team": "BOS",
                "away_team": "NYY",
                "game_type": "R",
            }
        )


def test_future_source_manifest_and_cross_file_duplicates(tmp_path):
    a, b = tmp_path / "a.csv", tmp_path / "b.csv"
    fixture_csv(a)
    fixture_csv(b)
    expected = {123: "2027-04-01"}
    result = scan([a], 2027, expected)
    assert result["rows"] == result["games"] == result["pitchers"] == 1
    assert result["production_write_allowed"] is False
    with pytest.raises(ReleaseError, match="Duplicate pitch"):
        scan([a, b], 2027, expected)
    with pytest.raises(ReleaseError, match="Historical"):
        scan([a], 2026, expected)
    with pytest.raises(ReleaseError, match="game IDs"):
        scan([a], 2027, {456: "2027-04-01"})
