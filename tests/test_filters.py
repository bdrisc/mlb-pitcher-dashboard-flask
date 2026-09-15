"""Unit tests for canonical pitch-filter parsing and validation."""

from datetime import date

import pytest
from werkzeug.datastructures import MultiDict

from app.services.filters import (
    FilterValidationError,
    PitchFilters,
    parse_pitch_filters,
)


def test_empty_query_returns_empty_filter_object():
    assert parse_pitch_filters(MultiDict()) == PitchFilters()


def test_parser_normalizes_aliases_repeated_values_and_dates():
    args = MultiDict(
        [
            ("pitcher", "  Sample, Pitcher "),
            ("team", "bos"),
            ("pitch_type", "ff, Slider"),
            ("pitch_type", "changeup,FF"),
            ("batter_side", "right,left"),
            ("season", "2026"),
            ("date_from", "2026-04-01"),
            ("date_to", "2026-09-30"),
            ("balls", "3"),
            ("strikes", "2"),
            ("home_away", "A"),
        ]
    )

    filters = parse_pitch_filters(args)

    assert filters.pitcher == "Sample, Pitcher"
    assert filters.team == "BOS"
    assert filters.pitch_types == ("FF", "SL", "CH")
    assert filters.batter_sides == ("R", "L")
    assert filters.season == 2026
    assert filters.date_from == date(2026, 4, 1)
    assert filters.date_to == date(2026, 9, 30)
    assert filters.balls == 3
    assert filters.strikes == 2
    assert filters.home_away == "away"


def test_parser_collects_multiple_errors_in_one_response():
    args = MultiDict(
        {
            "team": "Boston",
            "pitch_type": "gyroball",
            "batter_side": "switch",
            "season": "2007",
            "date_from": "April 1",
            "balls": "4",
            "strikes": "three",
            "home_away": "neutral",
            "unexpected": "value",
        }
    )

    with pytest.raises(FilterValidationError) as captured:
        parse_pitch_filters(args)

    assert set(captured.value.errors) == {
        "team",
        "pitch_type",
        "batter_side",
        "season",
        "date_from",
        "balls",
        "strikes",
        "home_away",
        "unexpected",
    }


def test_parser_rejects_repeated_scalar_filters():
    args = MultiDict([("season", "2025"), ("season", "2026")])

    with pytest.raises(FilterValidationError) as captured:
        parse_pitch_filters(args)

    assert captured.value.errors == {"season": ["must be supplied only once"]}


def test_parser_can_require_pitcher_without_duplicating_route_logic():
    with pytest.raises(FilterValidationError) as captured:
        parse_pitch_filters(MultiDict(), require_pitcher=True)

    assert captured.value.errors == {"pitcher": ["is required"]}
