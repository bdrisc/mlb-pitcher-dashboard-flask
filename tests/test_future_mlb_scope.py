"""Independent schedule and MLB identity replay and failure checks."""

import pytest

from scripts.acquire_future_mlb_scope import (
    acquire,
    fixtures,
    parse_people,
    parse_schedule,
    rebuild,
    verify,
)
from scripts.rehearse_snapshot_release import ReleaseError

PID = 2000000010
BID = 2000000011
FIRST = "2027-04-01"
LAST = "2027-04-02"


def staged():
    return {
        PID: {
            str(offset): {
                "game_pk": 2000000000 + offset,
                "game_date": f"2027-04-0{offset}",
                "pitcher": PID,
                "batter": BID,
                "player_name": "Fixture, Pitcher",
                "p_throws": "R",
                "stand": "R",
            }
            for offset in (1, 2)
        }
    }


def test_acquire_replay(tmp_path):
    stage = {"season": 2027, "synthetic": True}
    out = tmp_path / "scope"

    def no_network(url):
        pytest.fail("Unexpected network request")

    result = acquire(stage, staged(), out, "a" * 64, FIRST, LAST, fetch=no_network)
    assert len(result["completed_games"]) == 2
    assert len(result["people"]) == 2
    assert result["pitchers"] == result["batters"] == 1
    assert rebuild(
        stage, staged(), out / "raw", result["responses"], "a" * 64, FIRST, LAST
    ) == result
    (out / "raw" / "schedule.json").write_bytes(b"changed")
    with pytest.raises(ReleaseError, match="checksum"):
        rebuild(stage, staged(), out / "raw", result["responses"], "a" * 64, FIRST, LAST)


@pytest.mark.parametrize("failure", ["count", "game_type", "year", "unfinished", "duplicate"])
def test_reject_invalid_schedule(failure):
    payload = fixtures()["schedule"]
    game = payload["dates"][0]["games"][0]
    if failure == "count":
        payload["totalGames"] = 3
    elif failure == "game_type":
        game["gameType"] = "S"
    elif failure == "year":
        game["season"] = "2026"
    elif failure == "unfinished":
        game["status"]["detailedState"] = "Suspended"
    else:
        payload["dates"][1]["games"][0]["gamePk"] = game["gamePk"]
    with pytest.raises(ReleaseError):
        parse_schedule(payload, 2027, FIRST, LAST)


@pytest.mark.parametrize("failure", ["missing_game", "name", "throws", "bats"])
def test_reject_scope_conflict(failure):
    data = fixtures()
    games, _ = parse_schedule(data["schedule"], 2027, FIRST, LAST)
    people = parse_people(data["people_0000"], {PID, BID})
    if failure == "missing_game":
        games.pop(2000000001)
    elif failure == "name":
        people[PID]["name"] = "Someone Else"
    elif failure == "throws":
        people[PID]["throws"] = "L"
    else:
        people[BID]["bats"] = "L"
    with pytest.raises(ReleaseError):
        verify(staged(), games, people)


def test_missing_person():
    data = fixtures()["people_0000"]
    data["people"].pop()
    with pytest.raises(ReleaseError, match="Missing MLB"):
        parse_people(data, {PID, BID})
