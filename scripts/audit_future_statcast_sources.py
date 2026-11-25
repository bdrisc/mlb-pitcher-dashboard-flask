"""Offline source manifest for a future season; never connects to a database."""

from __future__ import annotations

import argparse
import csv
import gzip
import json
from datetime import date
from pathlib import Path

from scripts.rehearse_snapshot_release import ReleaseError, evidence, require, save

REQUIRED = {
    "game_date",
    "game_pk",
    "at_bat_number",
    "pitch_number",
    "pitch_type",
    "player_name",
    "pitcher",
    "batter",
    "stand",
    "p_throws",
    "balls",
    "strikes",
    "description",
    "type",
    "home_team",
    "away_team",
    "game_type",
}


def scan(paths, season, expected_games):
    require(season >= 2027, "Historical seasons are protected.")
    require(bool(paths) and bool(expected_games), "Require source files and reviewed schedule.")
    require(len({p.resolve() for p in paths}) == len(paths), "Repeated source file.")
    keys = set()
    games = {}
    pitchers = set()
    sources = []
    for path in paths:
        before = evidence(path)
        opener = gzip.open if path.suffix == ".gz" else open
        count = 0
        with opener(path, "rt", encoding="utf-8-sig", newline="") as handle:
            reader = csv.DictReader(handle)
            require(
                reader.fieldnames and REQUIRED <= set(reader.fieldnames),
                f"Missing required columns: {path.name}",
            )
            require(
                len(set(reader.fieldnames)) == len(reader.fieldnames),
                f"Duplicate CSV headers: {path.name}",
            )
            for row in reader:
                require(
                    None not in row and all(v is not None for v in row.values()),
                    f"Malformed CSV row: {path.name}",
                )
                day = date.fromisoformat(row["game_date"])
                game, ab, pitch = (
                    int(row[k]) for k in ("game_pk", "at_bat_number", "pitch_number")
                )
                key = (game, ab, pitch)
                require(
                    day.year == season and row["game_type"] == "R",
                    "Unexpected season or non-regular-season source row.",
                )
                require(game > 0 and ab > 0 and pitch > 0, "Invalid pitch natural key.")
                require(key not in keys, f"Duplicate pitch key across sources: {key}")
                keys.add(key)
                require(
                    0 <= int(row["balls"]) <= 3 and 0 <= int(row["strikes"]) <= 2, "Invalid count."
                )
                pitcher, batter = int(row["pitcher"]), int(row["batter"])
                require(pitcher > 0 and batter > 0, "Invalid player ID.")
                require(
                    row["stand"] in ("L", "R") and row["p_throws"] in ("L", "R"),
                    "Invalid handedness.",
                )
                require(
                    bool(row["description"]) and bool(row["home_team"]) and bool(row["away_team"]),
                    "Missing outcome or game metadata.",
                )
                require(row["type"] in ("B", "S", "X"), "Unexpected pitch outcome type.")
                game_record = (day.isoformat(), row["home_team"], row["away_team"])
                require(
                    games.setdefault(game, game_record) == game_record,
                    f"Conflicting game metadata: {game}",
                )
                pitchers.add(pitcher)
                count += 1
        require(count > 0 and evidence(path) == before, "Empty or changed source file.")
        sources.append({"file": path.name, "rows": count, **before})
    require(set(games) == set(expected_games), "Source game IDs differ from reviewed schedule.")
    require(
        all(games[k][0] == expected_games[k] for k in games),
        "Source game dates differ from reviewed schedule.",
    )
    return {
        "schema": 1,
        "status": "SOURCE_PREFLIGHT_PASS_NOT_INGESTED",
        "season": season,
        "rows": len(keys),
        "pitchers": len(pitchers),
        "games": len(games),
        "date_from": min(g[0] for g in games.values()),
        "date_to": max(g[0] for g in games.values()),
        "sources": sources,
        "production_write_allowed": False,
    }


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--season", type=int, required=True)
    parser.add_argument(
        "--schedule",
        type=Path,
        required=True,
        help="Reviewed JSON object mapping game IDs to ISO game dates.",
    )
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("sources", type=Path, nargs="+")
    args = parser.parse_args()
    try:
        schedule = json.loads(args.schedule.read_bytes())
        expected = {int(k): v for k, v in schedule.items()}
        result = scan(args.sources, args.season, expected)
        result["schedule"] = evidence(args.schedule)
        save(args.output, result)
        print(result["status"])
    except (ReleaseError, OSError, ValueError, TypeError, KeyError) as exc:
        print("SOURCE_PREFLIGHT_FAILED:", str(exc))
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
