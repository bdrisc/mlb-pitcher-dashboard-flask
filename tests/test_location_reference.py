"""Regression checks for the independently validated location reference."""

from datetime import date

import pytest

from app.services.filters import PitchFilters
from app.services.location_reference import _load_reference, shared_league_bins
from app.services.pitch_pair_effectiveness import _stable_round


@pytest.mark.parametrize(("hand", "expected"), [("L", 195), ("R", 256)])
def test_full_reference_bins(hand, expected):
    rows = shared_league_bins(PitchFilters(season=2026), hand)
    assert len(rows) == expected
    assert all(0 <= row["hard_hit_count"] <= row["ev_count"] <= row["batted_balls"] for row in rows)
    assert len({(r["pitch_type"], r["batter_side"], r["x"], r["y"]) for r in rows}) == expected


def test_full_reference_contact_total():
    assert (
        sum(
            row["batted_balls"]
            for hand in ("L", "R")
            for row in shared_league_bins(PitchFilters(season=2026), hand)
        )
        == 93353
    )


@pytest.mark.parametrize(
    ("hand", "filters", "expected"),
    [
        ("L", {"home_away": "home"}, 186),
        ("R", {"home_away": "home"}, 240),
        ("L", {"home_away": "away"}, 178),
        ("R", {"home_away": "away"}, 242),
        ("L", {"batter_sides": ("L",), "count_group": "ahead"}, 83),
        ("R", {"batter_sides": ("L",), "count_group": "ahead"}, 117),
        ("L", {"batter_sides": ("R",), "balls": 0, "strikes": 0}, 88),
        ("R", {"batter_sides": ("R",), "balls": 0, "strikes": 0}, 102),
        (
            "L",
            {
                "date_from": date(2026, 6, 1),
                "date_to": date(2026, 7, 31),
                "pitch_types": ("FF", "SL"),
            },
            36,
        ),
        (
            "R",
            {
                "date_from": date(2026, 6, 1),
                "date_to": date(2026, 7, 31),
                "pitch_types": ("FF", "SL"),
            },
            36,
        ),
        ("L", {"date_from": date(2026, 4, 1), "date_to": date(2026, 4, 1)}, 79),
        ("R", {"date_from": date(2026, 4, 1), "date_to": date(2026, 4, 1)}, 100),
        ("L", {"date_from": date(2026, 12, 1)}, 0),
        ("R", {"date_from": date(2026, 12, 1)}, 0),
    ],
)
def test_verified_filter_rollups(hand, filters, expected):
    assert len(shared_league_bins(PitchFilters(season=2026, **filters), hand)) == expected


def test_team_does_not_limit_reference():
    assert shared_league_bins(PitchFilters(season=2026, team="BOS"), "R") == shared_league_bins(
        PitchFilters(season=2026), "R"
    )


def test_invalid_reference_fails_closed(monkeypatch, tmp_path):
    from app.services import location_reference

    target = tmp_path / "bad.gz"
    target.write_bytes(b"not a verified reference")
    monkeypatch.setattr(location_reference, "REFERENCE_PATH", target)
    _load_reference.cache_clear()
    shared_league_bins.cache_clear()
    try:
        with pytest.raises(ValueError, match="checksum"):
            shared_league_bins(PitchFilters(season=2026), "R")
    finally:
        _load_reference.cache_clear()
        shared_league_bins.cache_clear()


@pytest.mark.parametrize(
    ("value", "digits", "expected"),
    [
        (0.7705, 3, 0.771),
        (-2.45, 1, -2.5),
        (0.45, 1, 0.5),
        (0.3935, 3, 0.394),
        (2.65, 1, 2.7),
        (0.7705 - 1e-7, 3, 0.770),
        (-2.45 + 1e-7, 1, -2.4),
    ],
)
def test_pair_rounding_midpoints(value, digits, expected):
    for jitter in (0, -1e-12, 1e-12):
        assert _stable_round(value + jitter, digits) == expected
