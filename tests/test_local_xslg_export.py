"""Read-only public-cohort xSLG export checks."""

import csv
import gzip
from datetime import date

import pytest

from scripts.export_local_xslg import write_export


def test_xslg_export_preserves_pitch_identity_without_extra_columns(tmp_path):
    destination = tmp_path / "xslg.csv.gz"
    rows = [
        {
            "pitch_id": "823573_45_5",
            "pitcher_id": 605400,
            "game_date": date(2026, 9, 17),
            "events": "single",
            "estimated_slg": 0.876,
        },
        {
            "pitch_id": "823573_13_1",
            "pitcher_id": 605400,
            "game_date": date(2026, 9, 17),
            "events": "field_out",
            "estimated_slg": None,
        },
    ]
    assert write_export(rows, destination) == 1
    with gzip.open(destination, "rt", encoding="utf-8", newline="") as source:
        output = list(csv.DictReader(source))
    assert output == [
        {
            "pitch_id": "823573_45_5",
            "pitcher_id": "605400",
            "game_date": "2026-09-17",
            "events": "single",
            "estimated_slg": "0.876",
        }
    ]


def test_xslg_export_rejects_implausible_values(tmp_path):
    rows = [
        {
            "pitch_id": "a",
            "pitcher_id": 605400,
            "game_date": date(2026, 9, 17),
            "events": "single",
            "estimated_slg": 4.1,
        }
    ]
    with pytest.raises(ValueError, match="Invalid xSLG"):
        write_export(rows, tmp_path / "invalid.csv.gz")
