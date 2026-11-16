"""Guardrails for read-only parity source exports."""

import csv
import gzip
from datetime import date

import pytest

from scripts.export_parity_inputs import (
    select_mismatched_pitchers,
    write_pitch_snapshot,
    write_published_snapshot,
)


def test_select_only_mismatched_pitchers():
    report = {
        "season": 2026,
        "results": [
            {
                "pitcher_id": 605400,
                "local_pitches": 2946,
                "public_pitches": 2946,
                "different_fields": 0,
            },
            {
                "pitcher_id": 592332,
                "local_pitches": 3003,
                "public_pitches": 3003,
                "different_fields": 207,
            },
        ],
    }
    assert select_mismatched_pitchers(report) == (2026, {592332: 3003})
    assert select_mismatched_pitchers(report, 592332) == (2026, {592332: 3003})
    with pytest.raises(ValueError, match="not mismatched"):
        select_mismatched_pitchers(report, 605400)


def test_export_keeps_nulls_and_date_and_checks_pitch_counts(tmp_path):
    path = tmp_path / "source.csv.gz"
    fields = ["pitch_id", "pitcher_id", "pitch_type", "arm_angle", "audit_game_date"]
    rows = [
        {
            "pitch_id": "823488_1_1",
            "pitcher_id": 592332,
            "pitch_type": "FF",
            "arm_angle": None,
            "audit_game_date": date(2026, 4, 3),
        },
        {
            "pitch_id": "823488_1_2",
            "pitcher_id": 592332,
            "pitch_type": "ST",
            "arm_angle": 42.4,
            "audit_game_date": date(2026, 4, 3),
        },
    ]
    assert write_pitch_snapshot(rows, path, fields, {592332: 2}) == 2
    with gzip.open(path, "rt", encoding="utf-8", newline="") as source:
        actual = list(csv.DictReader(source))
    assert actual[0]["arm_angle"] == ""
    assert actual[1]["arm_angle"] == "42.4"
    assert actual[0]["audit_game_date"] == "2026-04-03"
    with pytest.raises(ValueError, match="changed since audit"):
        write_pitch_snapshot(rows, path, fields, {592332: 3})
    assert not path.exists()


def test_export_refuses_duplicate_pitch_ids(tmp_path):
    path = tmp_path / "duplicate.csv.gz"
    rows = [
        {"pitch_id": "x", "pitcher_id": 592332},
        {"pitch_id": "x", "pitcher_id": 592332},
    ]
    with pytest.raises(ValueError, match="duplicate"):
        write_pitch_snapshot(rows, path, ["pitch_id", "pitcher_id"], {592332: 2})
    assert not path.exists()


def test_grades_csv_is_distinct_from_pitch_csv(tmp_path):
    output = tmp_path / "grades.csv.gz"
    rows = [{"mlb_id": 592332, "season": 2026, "category": "FF", "stuff_plus": 103.2}]
    fields = ["mlb_id", "season", "category", "stuff_plus"]
    assert write_published_snapshot(rows, output, fields) == 1
    with gzip.open(output, "rt", encoding="utf-8", newline="") as source:
        assert list(csv.DictReader(source))[0]["stuff_plus"] == "103.2"
