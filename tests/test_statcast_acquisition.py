"""Tests for resumable season downloads and production sample creation."""

from __future__ import annotations

import json
from datetime import date

import pandas as pd

import app.commands.statcast as statcast_commands
from app.services.statcast_acquisition import (
    DateChunk,
    acquire_statcast_chunk,
    build_top_pitcher_sample,
    filter_statcast_pitchers,
    iter_date_chunks,
    recent_statcast_chunk,
    season_date_range,
)


def _pitch_row(
    *,
    pitcher: int,
    player_name: str,
    game_pk: int,
    at_bat_number: int,
    pitch_number: int,
    game_date: str = "2026-04-01",
    game_type: str = "R",
) -> dict:
    return {
        "game_date": game_date,
        "game_pk": game_pk,
        "game_type": game_type,
        "at_bat_number": at_bat_number,
        "pitch_number": pitch_number,
        "pitch_type": "FF",
        "player_name": player_name,
        "pitcher": pitcher,
        "batter": 900000 + at_bat_number,
        "stand": "R",
        "p_throws": "R",
        "balls": 0,
        "strikes": 0,
        "description": "called_strike",
        "type": "S",
        "home_team": "BOS",
        "away_team": "NYY",
    }


def test_season_bounds_and_date_chunks_are_inclusive():
    start_date, end_date = season_date_range(
        2026,
        today=date(2026, 9, 15),
    )
    chunks = iter_date_chunks(start_date, end_date, 5)

    assert start_date == date(2026, 3, 15)
    assert end_date == date(2026, 9, 14)
    assert chunks[0] == DateChunk(date(2026, 3, 15), date(2026, 3, 19))
    assert chunks[-1].end_date == date(2026, 9, 14)
    assert all(
        current.end_date.toordinal() + 1 == following.start_date.toordinal()
        for current, following in zip(chunks, chunks[1:], strict=False)
    )


def test_recent_sync_window_overlaps_recent_days_and_stops_before_season():
    assert recent_statcast_chunk(
        lookback_days=4,
        today=date(2026, 9, 21),
    ) == DateChunk(date(2026, 9, 17), date(2026, 9, 20))
    assert recent_statcast_chunk(
        lookback_days=4,
        latest_game_date=date(2026, 9, 14),
        today=date(2026, 9, 21),
    ) == DateChunk(date(2026, 9, 11), date(2026, 9, 20))
    assert recent_statcast_chunk(today=date(2026, 3, 10)) is None


def test_filter_statcast_pitchers_preserves_only_the_deployed_cohort(tmp_path):
    source = tmp_path / "recent.csv.gz"
    destination = tmp_path / "selected.csv.gz"
    pd.DataFrame(
        [
            _pitch_row(
                pitcher=10,
                player_name="Alpha, Ace",
                game_pk=1,
                at_bat_number=1,
                pitch_number=1,
            ),
            _pitch_row(
                pitcher=20,
                player_name="Beta, Bob",
                game_pk=1,
                at_bat_number=2,
                pitch_number=1,
            ),
        ]
    ).to_csv(source, index=False, compression="gzip")

    selected_rows = filter_statcast_pitchers(source, destination, {20})

    assert selected_rows == 1
    assert pd.read_csv(destination)["pitcher"].tolist() == [20]


def test_recent_sync_command_skips_cleanly_without_a_deployed_cohort(app, monkeypatch):
    monkeypatch.setattr(
        statcast_commands,
        "recent_statcast_chunk",
        lambda **_kwargs: DateChunk(date(2026, 9, 17), date(2026, 9, 20)),
    )

    result = app.test_cli_runner().invoke(args=["statcast", "sync-recent", "--lookback-days", "4"])

    assert result.exit_code == 0
    assert "no deployed pitcher cohort exists" in result.output


def test_acquisition_filters_invalid_rows_and_reuses_cache(tmp_path):
    frame = pd.DataFrame(
        [
            _pitch_row(
                pitcher=10,
                player_name="Pitcher, One",
                game_pk=1,
                at_bat_number=1,
                pitch_number=1,
            ),
            _pitch_row(
                pitcher=20,
                player_name="Pitcher, Two",
                game_pk=1,
                at_bat_number=2,
                pitch_number=1,
            ),
            _pitch_row(
                pitcher=20,
                player_name="Pitcher, Two",
                game_pk=2,
                at_bat_number=1,
                pitch_number=1,
                game_type="S",
            ),
            {
                **_pitch_row(
                    pitcher=30,
                    player_name="Pitcher, Three",
                    game_pk=1,
                    at_bat_number=3,
                    pitch_number=1,
                ),
                "pitch_type": None,
            },
        ]
    )
    calls = 0

    def fetcher(_start, _end):
        nonlocal calls
        calls += 1
        return frame

    chunk = DateChunk(date(2026, 4, 1), date(2026, 4, 5))
    first = acquire_statcast_chunk(chunk, cache_dir=tmp_path, fetcher=fetcher)
    second = acquire_statcast_chunk(chunk, cache_dir=tmp_path, fetcher=fetcher)

    assert calls == 1
    assert first.source_rows == 4
    assert first.pitch_rows == 2
    assert first.dropped_rows == 2
    assert first.from_cache is False
    assert second.pitch_rows == 2
    assert second.from_cache is True
    assert first.path.exists()


def test_top_pitcher_sample_keeps_complete_histories_and_manifest(tmp_path):
    cache_dir = tmp_path / "cache"
    cache_dir.mkdir()
    first = pd.DataFrame(
        [
            _pitch_row(
                pitcher=10,
                player_name="Alpha, Ace",
                game_pk=1,
                at_bat_number=1,
                pitch_number=1,
            ),
            _pitch_row(
                pitcher=10,
                player_name="Alpha, Ace",
                game_pk=1,
                at_bat_number=1,
                pitch_number=2,
            ),
            _pitch_row(
                pitcher=20,
                player_name="Beta, Bob",
                game_pk=1,
                at_bat_number=2,
                pitch_number=1,
            ),
        ]
    )
    second = pd.DataFrame(
        [
            _pitch_row(
                pitcher=10,
                player_name="Alpha, Ace",
                game_pk=1,
                at_bat_number=1,
                pitch_number=2,
            ),
            _pitch_row(
                pitcher=10,
                player_name="Alpha, Ace",
                game_pk=2,
                at_bat_number=1,
                pitch_number=1,
                game_date="2026-04-06",
            ),
            _pitch_row(
                pitcher=20,
                player_name="Beta, Bob",
                game_pk=2,
                at_bat_number=2,
                pitch_number=1,
                game_date="2026-04-06",
            ),
            _pitch_row(
                pitcher=30,
                player_name="Gamma, Gus",
                game_pk=2,
                at_bat_number=3,
                pitch_number=1,
                game_date="2026-04-06",
            ),
        ]
    )
    first.to_csv(cache_dir / "statcast_2026-04-01_2026-04-05.csv.gz", index=False)
    second.to_csv(cache_dir / "statcast_2026-04-06_2026-04-10.csv.gz", index=False)
    output = tmp_path / "production_statcast_2026.csv.gz"

    report = build_top_pitcher_sample(
        season=2026,
        cache_dir=cache_dir,
        output_path=output,
        pitcher_limit=2,
    )

    exported = pd.read_csv(output)
    manifest = json.loads(report.manifest_path.read_text(encoding="utf-8"))
    assert report.pitcher_count == 2
    assert report.pitch_count == 5
    assert set(exported["pitcher"]) == {10, 20}
    assert exported.groupby("pitcher").size().to_dict() == {10: 3, 20: 2}
    assert [pitcher["pitch_count"] for pitcher in manifest["pitchers"]] == [3, 2]
    assert [pitcher["name"] for pitcher in manifest["pitchers"]] == [
        "Ace Alpha",
        "Bob Beta",
    ]
