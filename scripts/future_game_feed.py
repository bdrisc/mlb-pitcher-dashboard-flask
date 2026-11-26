"""Strict game-feed pitch identity, ownership and team coverage checks."""

from __future__ import annotations

import json
import time
from collections import defaultdict

from scripts.acquire_future_leaderboards import digest, strict_json
from scripts.acquire_future_savant import MAX_BYTES, download, timestamp
from scripts.rehearse_snapshot_release import require, save

ORIGIN = "https://statsapi.mlb.com/api/v1.1/game"
TEAM_ALIASES = {
    "AZ": "ARI",
    "CHW": "CWS",
    "KCR": "KC",
    "SDP": "SD",
    "SFG": "SF",
    "TBR": "TB",
    "WSN": "WSH",
}


def team(code):
    require(isinstance(code, str) and bool(code), "Missing team abbreviation.")
    return TEAM_ALIASES.get(code, code)


def group_games(staged):
    games = defaultdict(dict)
    for rows in staged.values():
        for key, row in rows.items():
            require(key not in games[row["game_pk"]], "Duplicate staged pitch.")
            games[row["game_pk"]][key] = row
    return dict(games)


def parse_feed(payload, game, day, season):
    metadata = payload["gameData"]
    identity = metadata["game"]
    status = metadata["status"]
    require(
        payload["gamePk"] == identity["pk"] == game
        and str(identity["season"]) == str(season)
        and identity["type"] == "R"
        and metadata["datetime"]["officialDate"] == day
        and status["abstractGameState"] == "Final"
        and status["detailedState"] in ("Final", "Game Over", "Completed Early"),
        "Game-feed identity, date, season or completion mismatch.",
    )
    home = team(metadata["teams"]["home"]["abbreviation"])
    away = team(metadata["teams"]["away"]["abbreviation"])
    require(home != away, "Identical home and away teams.")
    pitches, seen_ab, nonpitch_plays = {}, set(), []
    plays = payload["liveData"]["plays"]["allPlays"]
    require(isinstance(plays, list) and bool(plays), "Missing game plays.")
    for play in plays:
        about = play["about"]
        ab = about["atBatIndex"]
        require(
            type(ab) is int and ab >= 0 and ab not in seen_ab,
            "Duplicate or invalid at-bat index.",
        )
        seen_ab.add(ab)
        match = play["matchup"]
        owner = match["pitcher"]["id"]
        batter = match["batter"]["id"]
        require(
            type(owner) is int and owner > 0 and type(batter) is int and batter > 0,
            "Missing pitch owner or batter.",
        )
        hand = match["pitchHand"]["code"]
        side = match["batSide"]["code"]
        require(hand in ("L", "R") and side in ("L", "R"), "Unsupported game-feed hand.")
        count = 0
        for event in play["playEvents"]:
            details = event.get("details", {})
            text = " ".join(
                str(details.get(key, "")) for key in ("description", "event", "eventType")
            ).lower()
            require(
                not any(
                    token in text
                    for token in ("automatic ball", "automatic strike", "pitch timer violation")
                ),
                "Automatic count event requires independent normalization review.",
            )
            if count:
                require(
                    details.get("eventType")
                    not in ("pitching_substitution", "offensive_substitution")
                    and "pitching substitution" not in text
                    and "offensive substitution" not in text,
                    "Mid-PA substitution requires pitch-level ownership review.",
                )
            if event.get("isPitch") is not True:
                continue
            number = event["pitchNumber"]
            require(type(number) is int and number == count + 1, "Nonsequential pitch number.")
            key = f"{game}_{ab + 1}_{number}"
            require(key not in pitches, "Duplicate game-feed pitch key.")
            pitches[key] = (owner, batter, hand, side, home, away)
            count += 1
        if not count:
            nonpitch_plays.append(ab + 1)
    require(bool(pitches), "No game-feed physical pitches.")
    return pitches, nonpitch_plays


def compare_game(staged, payload, game, day, season):
    pitches, nonpitch = parse_feed(payload, game, day, season)
    require(
        set(pitches) == set(staged),
        f"Pitch key coverage mismatch for game {game}: "
        f"missing={len(pitches.keys() - staged.keys())}, "
        f"extra={len(staged.keys() - pitches.keys())}.",
    )
    for key, row in staged.items():
        require(
            row["description"] not in ("automatic_ball", "automatic_strike"),
            "Staged automatic event requires independent normalization review.",
        )
        expected = (
            row["pitcher"],
            row["batter"],
            row["p_throws"],
            row["stand"],
            team(row["home_team"]),
            team(row["away_team"]),
        )
        require(pitches[key] == expected, f"Pitch owner, hand or team mismatch: {key}")
    return {"physical_pitches": len(pitches), "nonpitch_at_bats": nonpitch}


def fixture(game):
    return {
        "gamePk": game,
        "gameData": {
            "game": {"pk": game, "season": "2027", "type": "R"},
            "datetime": {"officialDate": f"2027-04-0{game - 2000000000}"},
            "status": {"abstractGameState": "Final", "detailedState": "Final"},
            "teams": {"home": {"abbreviation": "BOS"}, "away": {"abbreviation": "NYY"}},
        },
        "liveData": {
            "plays": {
                "allPlays": [
                    {
                        "about": {"atBatIndex": 0},
                        "matchup": {
                            "pitcher": {"id": 2000000010},
                            "batter": {"id": 2000000011},
                            "pitchHand": {"code": "R"},
                            "batSide": {"code": "R"},
                        },
                        "playEvents": [
                            {"isPitch": True, "pitchNumber": number, "details": {}}
                            for number in (1, 2, 3)
                        ],
                    }
                ]
            }
        },
    }


def feed_url(game):
    return f"{ORIGIN}/{game}/feed/live"


def acquire(raw, game_ids, synthetic, fetch=download, delay=0.25):
    raw.mkdir(parents=True, exist_ok=False)
    records = {}
    for game in sorted(game_ids):
        url = feed_url(game)
        started = timestamp()
        data, status, content_type = (
            (json.dumps(fixture(game)).encode(), 200, "application/json")
            if synthetic
            else fetch(url)
        )
        require(status == 200 and 0 < len(data) <= MAX_BYTES, "Invalid game-feed response.")
        name = f"{game}.json"
        with (raw / name).open("xb") as handle:
            handle.write(data)
        record = {
            "file": name,
            "url": url,
            "started_utc": started,
            "received_utc": timestamp(),
            "http_status": status,
            "content_type": content_type,
            "synthetic": synthetic,
            "bytes": len(data),
            "sha256": digest(data),
        }
        save(raw / f"{name}.meta.json", record)
        records[str(game)] = record
        if not synthetic:
            time.sleep(delay)
    return records


def replay(raw, records, staged, completed_games, season, synthetic):
    grouped = group_games(staged)
    require(
        set(records) == set(completed_games) == {str(game) for game in grouped},
        "Game-feed population differs from approved completed games.",
    )
    results = {}
    for game, rows in sorted(grouped.items()):
        name = f"{game}.json"
        record = records[str(game)]
        require(
            record["file"] == name
            and record["url"] == feed_url(game)
            and record["http_status"] == 200
            and record["synthetic"] is synthetic
            and json.loads((raw / f"{name}.meta.json").read_bytes()) == record,
            "Game-feed archive provenance mismatch.",
        )
        data = (raw / name).read_bytes()
        require(
            0 < len(data) <= MAX_BYTES
            and len(data) == record["bytes"]
            and digest(data) == record["sha256"],
            "Game-feed checksum mismatch.",
        )
        results[str(game)] = compare_game(
            rows, strict_json(data), game, completed_games[str(game)], season
        )
    return results
