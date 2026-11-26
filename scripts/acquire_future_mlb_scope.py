"""Read-only MLB Stats API schedule and player identity evidence for staged seasons."""

from __future__ import annotations

import argparse
import json
import unicodedata
from datetime import date, datetime, timezone
from pathlib import Path
from urllib.parse import urlencode

from scripts.acquire_future_leaderboards import digest, strict_json
from scripts.acquire_future_savant import MAX_BYTES, download, timestamp
from scripts.reconcile_future_sources import read_staged_sources
from scripts.rehearse_snapshot_release import ReleaseError, require, save, sha

ORIGIN = "https://statsapi.mlb.com/api/v1"
BATCH = 100


def window(season, first, last, synthetic):
    start, end = date.fromisoformat(first), date.fromisoformat(last)
    require(
        start.isoformat() == first
        and end.isoformat() == last
        and start.year == end.year == season
        and season >= 2027
        and start <= end,
        "Invalid future-season date window.",
    )
    if synthetic:
        require((first, last) == ("2027-04-01", "2027-04-02"), "Wrong fixture window.")
    else:
        require(end < datetime.now(timezone.utc).date(), "Window must be in the past.")


def populations(staged):
    games, pitchers, batters = {}, {}, {}
    for pid, rows in staged.items():
        for row in rows.values():
            game, day = row["game_pk"], row["game_date"]
            require(games.setdefault(game, day) == day, "Conflicting staged game date.")
            require(pid == row["pitcher"], "Conflicting staged pitcher ID.")
            pitchers.setdefault(pid, set()).add((row["player_name"], row["p_throws"]))
            batters.setdefault(row["batter"], set()).add(row["stand"])
    return games, pitchers, batters


def specs(season, first, last, staged):
    _, pitchers, batters = populations(staged)
    ids = sorted(pitchers.keys() | batters.keys())
    result = {
        "schedule": (
            "/schedule",
            dict(sportId=1, gameType="R", season=season, startDate=first, endDate=last),
        )
    }
    for offset in range(0, len(ids), BATCH):
        result[f"people_{offset // BATCH:04d}"] = (
            "/people",
            {"personIds": ",".join(map(str, ids[offset : offset + BATCH]))},
        )
    return result


def parse_schedule(payload, season, first, last):
    games, excluded, seen, dates = {}, {}, set(), set()
    require(isinstance(payload["dates"], list), "Invalid schedule response.")
    count = 0
    for day in payload["dates"]:
        day_date = day["date"]
        require(first <= day_date <= last and day_date not in dates, "Invalid schedule date.")
        dates.add(day_date)
        require(
            type(day["totalGames"]) is int and day["totalGames"] == len(day["games"]),
            "Incomplete schedule day.",
        )
        for game in day["games"]:
            pid = game["gamePk"]
            require(type(pid) is int and pid > 0 and pid not in seen, "Duplicate or invalid game.")
            seen.add(pid)
            count += 1
            require(
                game["gameType"] == "R"
                and str(game["season"]) == str(season)
                and game["officialDate"] == day_date,
                "Schedule season, game type or official date differs.",
            )
            status = game["status"]
            state = status["detailedState"]
            if state in ("Postponed", "Cancelled", "Canceled"):
                excluded[str(pid)] = {"date": day_date, "status": state}
            else:
                require(
                    status["abstractGameState"] == "Final"
                    and state in ("Final", "Game Over", "Completed Early"),
                    "Unresolved or unsupported game status; review before proceeding.",
                )
                games[pid] = day_date
    require(
        type(payload["totalGames"]) is int and count == payload["totalGames"],
        "Incomplete MLB schedule response.",
    )
    require(bool(games), "No completed regular-season games.")
    return games, excluded


def normalized_name(name):
    require(isinstance(name, str) and bool(name.strip()), "Missing player name.")
    if "," in name:
        pieces = name.split(",")
        require(len(pieces) == 2, "Ambiguous player name.")
        name = f"{pieces[1]} {pieces[0]}"
    name = unicodedata.normalize("NFKD", name.casefold())
    return "".join(ch for ch in name if ch.isalnum())


def parse_people(payload, ids):
    result = {}
    for row in payload["people"]:
        pid = row["id"]
        require(type(pid) is int and pid in ids and pid not in result, "Unexpected person ID.")
        name = row["fullName"]
        normalized_name(name)
        throws = row.get("pitchHand", {}).get("code")
        bats = row.get("batSide", {}).get("code")
        result[pid] = {"name": name, "throws": throws, "bats": bats}
    require(set(result) == ids, "Missing MLB person IDs.")
    return result


def verify(staged, games, people):
    expected_games, pitchers, batters = populations(staged)
    require(games == expected_games, "Completed-game IDs or dates differ from staged coverage.")
    require(set(people) == pitchers.keys() | batters.keys(), "MLB identity coverage differs.")
    for pid, observations in pitchers.items():
        person = people[pid]
        require(
            all(
                normalized_name(name) == normalized_name(person["name"])
                and hand == person["throws"]
                for name, hand in observations
            ),
            f"Pitcher name or throwing hand mismatch: {pid}",
        )
    for pid, sides in batters.items():
        bats = people[pid]["bats"]
        require(
            bats in ("L", "R", "S") and sides <= ({"L", "R"} if bats == "S" else {bats}),
            f"Batter handedness mismatch: {pid}",
        )


def fixtures():
    days = []
    for offset in (1, 2):
        day = f"2027-04-0{offset}"
        game = {
            "gamePk": 2000000000 + offset,
            "gameType": "R",
            "season": "2027",
            "officialDate": day,
            "status": {"abstractGameState": "Final", "detailedState": "Final"},
        }
        days.append({"date": day, "totalGames": 1, "games": [game]})
    people = [
        {
            "id": 2000000010,
            "fullName": "Pitcher Fixture",
            "pitchHand": {"code": "R"},
            "batSide": {"code": "R"},
        },
        {
            "id": 2000000011,
            "fullName": "Batter Fixture",
            "pitchHand": {"code": "R"},
            "batSide": {"code": "R"},
        },
    ]
    return {
        "schedule": {"totalGames": 2, "dates": days},
        "people_0000": {"people": people},
    }


def rebuild(stage, staged, raw, records, staging_sha, first, last):
    season = stage["season"]
    window(season, first, last, stage["synthetic"])
    expected = specs(season, first, last, staged)
    require(set(records) == set(expected), "Missing or extra MLB source archive.")
    people = {}
    for kind, (path, params) in expected.items():
        record = records[kind]
        name = f"{kind}.json"
        require(
            record["file"] == name
            and record["url"] == ORIGIN + path + "?" + urlencode(params)
            and record["parameters"] == params
            and record["synthetic"] is stage["synthetic"]
            and record["http_status"] == 200
            and json.loads((raw / f"{name}.meta.json").read_bytes()) == record,
            "MLB source provenance mismatch.",
        )
        data = (raw / name).read_bytes()
        require(
            0 < len(data) <= MAX_BYTES
            and len(data) == record["bytes"]
            and digest(data) == record["sha256"],
            "MLB archive checksum mismatch.",
        )
        payload = strict_json(data)
        if kind == "schedule":
            games, excluded = parse_schedule(payload, season, first, last)
        else:
            batch = parse_people(payload, {int(v) for v in params["personIds"].split(",")})
            require(not (people.keys() & batch.keys()), "Duplicate people across batches.")
            people.update(batch)
    verify(staged, games, people)
    _, pitchers, batters = populations(staged)
    return {
        "schema": 1,
        "status": "MLB_SCOPE_EVIDENCE_PASS_NOT_APPLIED",
        "season": season,
        "synthetic": stage["synthetic"],
        "staging_report_sha256": staging_sha,
        "window": {"start": first, "end": last},
        "completed_games": {str(k): v for k, v in sorted(games.items())},
        "excluded_games": excluded,
        "people": {str(k): v for k, v in sorted(people.items())},
        "pitchers": len(pitchers),
        "batters": len(batters),
        "responses": records,
        "independent_fangraphs_crosswalk_required": True,
        "pitch_event_completeness_review_required": True,
        "production_write_allowed": False,
    }


def acquire(stage, staged, output, staging_sha, first, last, fetch=download):
    window(stage["season"], first, last, stage["synthetic"])
    output.mkdir(parents=True, exist_ok=False)
    raw = output / "raw"
    raw.mkdir()
    records = {}
    fixture = fixtures() if stage["synthetic"] else None
    for kind, (path, params) in specs(stage["season"], first, last, staged).items():
        url = ORIGIN + path + "?" + urlencode(params)
        started = timestamp()
        data, status, content_type = (
            (json.dumps(fixture[kind]).encode(), 200, "application/json")
            if fixture is not None
            else fetch(url)
        )
        require(status == 200 and 0 < len(data) <= MAX_BYTES, "Invalid MLB HTTP response.")
        name = f"{kind}.json"
        with (raw / name).open("xb") as handle:
            handle.write(data)
        record = dict(
            file=name,
            url=url,
            parameters=params,
            started_utc=started,
            received_utc=timestamp(),
            http_status=status,
            content_type=content_type,
            synthetic=stage["synthetic"],
            bytes=len(data),
            sha256=digest(data),
        )
        save(raw / f"{name}.meta.json", record)
        records[kind] = record
        print(f"Archived {kind}", flush=True)
    result = rebuild(stage, staged, raw, records, staging_sha, first, last)
    save(output / "mlb_scope_evidence.json", result)
    return result


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--staging-report", type=Path, required=True)
    parser.add_argument("--staging-sha", required=True)
    parser.add_argument("--start", required=True)
    parser.add_argument("--end", required=True)
    parser.add_argument("--synthetic", action="store_true")
    parser.add_argument("--output", type=Path)
    parser.add_argument("--verify-report", type=Path)
    parser.add_argument("--report-sha")
    args = parser.parse_args()
    try:
        require(bool(args.output) != bool(args.verify_report), "Choose acquisition or replay.")
        stage, staged = read_staged_sources(args.staging_report, args.staging_sha)
        require(args.synthetic is stage["synthetic"], "Synthetic/real scope mismatch.")
        if args.verify_report:
            path = args.verify_report
            require(sha(path) == args.report_sha, "Report checksum mismatch.")
            result = json.loads(path.read_bytes())
            rebuilt = rebuild(
                stage,
                staged,
                path.parent / "raw",
                result["responses"],
                args.staging_sha,
                args.start,
                args.end,
            )
            require(result == rebuilt and sha(path) == args.report_sha, "Replay differs.")
        else:
            require(not args.report_sha, "Report checksum applies only to replay.")
            result = acquire(
                stage, staged, args.output, args.staging_sha, args.start, args.end
            )
            path = args.output / "mlb_scope_evidence.json"
        require(sha(args.staging_report) == args.staging_sha, "Staging report changed.")
        print(f"Completed games: {len(result['completed_games'])}")
        print(f"Pitchers: {result['pitchers']}; batters: {result['batters']}")
        print(f"Unique MLB people: {len(result['people'])}")
        print(f"Report SHA-256: {sha(path)}")
        print(result["status"])
        print("No database writes or publication performed.")
        return 0
    except Exception as exc:
        print(
            "MLB_SCOPE_FAILED:", str(exc) if isinstance(exc, ValueError) else type(exc).__name__
        )
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
