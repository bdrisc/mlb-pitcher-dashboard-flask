"""Movement-vs-AVG reference tests: full-MLB sampling, hand and angle rules."""

import csv
import gzip

import pytest

from app.services import movement_reference as reference


def _write_reference(path, records):
    with gzip.open(path, "wt", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=reference.REFERENCE_FIELDS)
        writer.writeheader()
        writer.writerows(records)


def _row(pitcher, side, pitch, angle, count, hb, ivb):
    return {
        "pitcher_id": pitcher,
        "pitch_type": pitch,
        "hand": side,
        "arm_angle_bin": angle,
        "pitch_count": count,
        "hb_sum": count * hb,
        "ivb_sum": count * ivb,
    }


def test_2026_movement_vs_average_is_same_type_hand_and_arm_angle(tmp_path, monkeypatch):
    path = tmp_path / "league_movement_2026.csv.gz"
    records = [
        _row(pitcher, "R", "FF", 42, 25, -8.0, 16.0)
        for pitcher in range(100, 105)
    ]
    records.extend(
        [
            _row(200, "R", "FF", 70, 1000, -25, 25),
            _row(201, "R", "SL", 42, 1000, -15, 2),
            _row(202, "L", "FF", 42, 1000, 10, 20),
        ]
    )
    _write_reference(path, records)
    monkeypatch.setattr(reference, "reference_path", lambda season: path)
    reference._load_reference.cache_clear()

    result = reference.movement_vs_average(
        season=2026,
        pitch_type="FF",
        throwing_hand="R",
        arm_angle=42.0,
        horizontal_break=-8.5,
        vertical_break=16.5,
    )
    assert result["hb_vs_avg"] == 0.5
    assert result["ivb_vs_avg"] == 0.5
    assert result["movement_avg_pitchers"] == 5
    assert result["movement_avg_pitches"] == 125


def test_2026_movement_vs_average_requires_minimum_comparison_sample(tmp_path, monkeypatch):
    path = tmp_path / "league_movement_2026.csv.gz"
    _write_reference(path, [_row(999, "R", "FF", 42, 125, -8, 16)])
    monkeypatch.setattr(reference, "reference_path", lambda season: path)
    reference._load_reference.cache_clear()
    result = reference.movement_vs_average(
        season=2026, pitch_type="FF", throwing_hand="R", arm_angle=42,
        horizontal_break=-8.5, vertical_break=16.5,
    )
    assert result["hb_vs_avg"] is None
    assert result["ivb_vs_avg"] is None
    assert result["movement_avg_pitchers"] == 1


def test_movement_vs_avg_missing_file_returns_unavailable(tmp_path, monkeypatch):
    monkeypatch.setattr(reference, "reference_path", lambda season: tmp_path / "missing.gz")
    result = reference.movement_vs_average(
        season=2026, pitch_type="FF", throwing_hand="R", arm_angle=42,
        horizontal_break=-8, vertical_break=16,
    )
    assert result["hb_vs_avg"] is None
    assert result["ivb_vs_avg"] is None


def test_full_league_export_refuses_public_cohort_and_empty_test_db(app, tmp_path):
    with app.app_context():
        with pytest.raises(ValueError, match="Not a full MLB season"):
            reference.export_full_league_reference(2026, tmp_path / "reference.gz")
    assert not (tmp_path / "reference.gz").exists()
