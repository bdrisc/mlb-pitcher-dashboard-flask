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
    records = [_row(pitcher, "R", "FF", 42, 25, -8.0, 16.0) for pitcher in range(100, 105)]
    records.extend(
        [
            _row(200, "R", "FF", 70, 1000, -25, 25),
            _row(201, "R", "SL", 42, 1000, -15, 2),
            _row(202, "L", "FF", 42, 1000, 10, 20),
        ]
    )
    _write_reference(path, records)
    monkeypatch.setattr(reference, "reference_path", lambda season: path)
    monkeypatch.setattr(reference, "compact_reference_path", lambda season: tmp_path / "none.b85")
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
    monkeypatch.setattr(reference, "compact_reference_path", lambda season: tmp_path / "none.b85")
    reference._load_reference.cache_clear()
    result = reference.movement_vs_average(
        season=2026,
        pitch_type="FF",
        throwing_hand="R",
        arm_angle=42,
        horizontal_break=-8.5,
        vertical_break=16.5,
    )
    assert result["hb_vs_avg"] is None
    assert result["ivb_vs_avg"] is None
    assert result["movement_avg_pitchers"] == 1


def test_movement_vs_avg_missing_file_returns_unavailable(tmp_path, monkeypatch):
    monkeypatch.setattr(reference, "reference_path", lambda season: tmp_path / "missing.gz")
    monkeypatch.setattr(
        reference, "compact_reference_path", lambda season: tmp_path / "missing.b85"
    )
    result = reference.movement_vs_average(
        season=2026,
        pitch_type="FF",
        throwing_hand="R",
        arm_angle=42,
        horizontal_break=-8,
        vertical_break=16,
    )
    assert result["hb_vs_avg"] is None
    assert result["ivb_vs_avg"] is None


def test_full_league_export_refuses_public_cohort_and_empty_test_db(app, tmp_path):
    with app.app_context():
        with pytest.raises(ValueError, match="Not a full MLB season"):
            reference.export_full_league_reference(2026, tmp_path / "reference.gz")
    assert not (tmp_path / "reference.gz").exists()


def test_packaged_2026_reference_matches_uploaded_full_league_source(tmp_path, monkeypatch):
    path = reference.compact_reference_path(2026)
    assert path.is_file()
    bins, distinct = reference._load_compact_reference(str(path), path.stat().st_mtime_ns)
    assert len(bins) == 30
    assert sum(len(rows) for rows in bins.values()) == 1927
    assert sum(row[1] for rows in bins.values() for row in rows) == 708337
    assert len(distinct) == 2501

    right_fastball = reference.movement_vs_average(
        season=2026,
        pitch_type="FF",
        throwing_hand="R",
        arm_angle=42.0,
        horizontal_break=-8.0,
        vertical_break=17.0,
    )
    assert right_fastball["movement_avg_pitchers"] == 385
    assert right_fastball["movement_avg_pitches"] == 53181
    assert right_fastball["hb_vs_avg"] == 0.5
    assert right_fastball["ivb_vs_avg"] == 0.8

    left_changeup = reference.movement_vs_average(
        season=2026,
        pitch_type="CH",
        throwing_hand="L",
        arm_angle=55.0,
        horizontal_break=12.0,
        vertical_break=10.0,
    )
    assert left_changeup["movement_avg_pitchers"] == 51
    assert left_changeup["movement_avg_pitches"] == 1648
    assert left_changeup["hb_vs_avg"] == -0.2
    assert left_changeup["ivb_vs_avg"] == 0.7

    monkeypatch.setattr(reference, "reference_path", lambda season: tmp_path / "missing.gz")
    monkeypatch.setattr(
        reference, "compact_reference_path", lambda season: tmp_path / "missing.b85"
    )

    assert (
        reference.movement_vs_average(
            season=2025,
            pitch_type="FF",
            throwing_hand="R",
            arm_angle=42.0,
            horizontal_break=-8.0,
            vertical_break=17.0,
        )["hb_vs_avg"]
        is None
    )


@pytest.mark.parametrize(
    ("angle", "expected"),
    [
        (47.95 - 1e-12, 48.0),
        (47.95 + 1e-12, 48.0),
        (54.35 - 1e-12, 54.4),
        (54.35 + 1e-12, 54.4),
    ],
)
def test_movement_arm_angle_rounding_is_stable(angle, expected):
    result = reference.movement_vs_average(
        season=2026,
        pitch_type="FF",
        throwing_hand="R",
        arm_angle=angle,
        horizontal_break=-8.0,
        vertical_break=17.0,
    )
    assert result["movement_avg_arm_angle"] == expected


@pytest.mark.parametrize("compact", [False, True])
@pytest.mark.parametrize(
    ("angle", "expected_count"),
    [
        (42.5 - 1e-12, 150),
        (42.5 + 1e-12, 150),
        (42.5 - 1e-7, 100),
        (42.5 + 1e-7, 100),
    ],
)
def test_movement_reference_window_is_stable(tmp_path, monkeypatch, compact, angle, expected_count):
    csv_path = tmp_path / "reference.csv.gz"
    packed_path = tmp_path / "reference.b85"
    monkeypatch.setattr(reference, "reference_path", lambda season: csv_path)
    monkeypatch.setattr(reference, "compact_reference_path", lambda season: packed_path)
    _write_reference(
        csv_path,
        [_row(p, "R", "FF", b, 10, -8.0, 16.0) for p in range(100, 105) for b in (37, 42, 47)],
    )
    if compact:
        packed_path.touch()
        monkeypatch.setattr(
            reference,
            "_load_compact_reference",
            lambda *args: (
                {("R", "FF"): [(b, 50, -400.0, 800.0) for b in (37, 42, 47)]},
                {(("R", "FF"), 37): (5, 5), (("R", "FF"), 38): (5, 5)},
            ),
        )
    result = reference.movement_vs_average(
        season=2026,
        pitch_type="FF",
        throwing_hand="R",
        arm_angle=angle,
        horizontal_break=-8.05,
        vertical_break=16.05,
    )
    assert result["movement_avg_pitches"] == expected_count
    assert result["hb_vs_avg"] == 0.1
    assert result["ivb_vs_avg"] == 0.1
