"""Package A game-feed completeness and coverage regression checks."""

from copy import deepcopy

import pytest

from scripts import future_game_feed as feed
from scripts.rehearse_snapshot_release import ReleaseError
from scripts.validate_future_release_evidence import clean_coverage, finish

GAME = 2000000001
DAY = "2027-04-01"


def staged():
    return {
        f"{GAME}_1_{number}": {
            "game_pk": GAME,
            "pitcher": 2000000010,
            "batter": 2000000011,
            "p_throws": "R",
            "stand": "R",
            "home_team": "BOS",
            "away_team": "NYY",
            "description": "called_strike",
        }
        for number in (1, 2, 3)
    }


@pytest.mark.parametrize(
    "failure",
    ["missing", "extra", "owner", "batter", "hand", "team", "date", "season", "automatic", "sub"],
)
def test_game_feed_conflict(failure):
    payload = feed.fixture(GAME)
    rows = staged()
    play = payload["liveData"]["plays"]["allPlays"][0]
    if failure == "missing":
        rows.pop(f"{GAME}_1_3")
    elif failure == "extra":
        play["playEvents"].pop()
    elif failure == "owner":
        play["matchup"]["pitcher"]["id"] = 123
    elif failure == "batter":
        play["matchup"]["batter"]["id"] = 123
    elif failure == "hand":
        play["matchup"]["pitchHand"]["code"] = "L"
    elif failure == "team":
        payload["gameData"]["teams"]["away"]["abbreviation"] = "SEA"
    elif failure == "date":
        payload["gameData"]["datetime"]["officialDate"] = "2027-04-02"
    elif failure == "season":
        payload["gameData"]["game"]["season"] = "2026"
    elif failure == "automatic":
        play["playEvents"][0]["details"]["description"] = "Automatic Ball"
    else:
        play["playEvents"].insert(
            1, {"isPitch": False, "details": {"eventType": "pitching_substitution"}}
        )
    with pytest.raises(ReleaseError):
        feed.compare_game(rows, payload, GAME, DAY, 2027)


def test_archive_replay(tmp_path):
    def no_network(url):
        pytest.fail("Synthetic replay cannot access network.")

    raw = tmp_path / "raw"
    records = feed.acquire(raw, [GAME], True, fetch=no_network)
    source = {2000000010: staged()}
    expected = {str(GAME): DAY}
    result = feed.replay(raw, records, source, expected, 2027, True)
    assert result == {str(GAME): {"physical_pitches": 3, "nonpitch_at_bats": []}}
    (raw / f"{GAME}.json").write_bytes(b"changed")
    with pytest.raises(ReleaseError, match="checksum"):
        feed.replay(raw, records, source, expected, 2027, True)


def test_team_alias_and_nonpitch_plays():
    payload = feed.fixture(GAME)
    payload["gameData"]["teams"]["away"]["abbreviation"] = "CHW"
    rows = staged()
    for row in rows.values():
        row["away_team"] = "CWS"
    plays = payload["liveData"]["plays"]["allPlays"]
    extra = deepcopy(plays[0])
    extra["about"]["atBatIndex"] = 1
    extra["playEvents"] = []
    plays.append(extra)
    assert feed.compare_game(rows, payload, GAME, DAY, 2027)["nonpitch_at_bats"] == [2]


def test_coverage_and_final_gate():
    leaderboard = {
        "coverage": {"fg": {"missing_staged_pitchers": [], "outside_staging_pitchers": []}},
        "missing_values": [],
        "unmapped_fangraphs_grades": [],
        "unmapped_fangraphs_rates": [],
        "spin_season_in_response": True,
    }
    reviewed = (
        {"synthetic": True, "season": 2027},
        {2000000010: staged()},
        leaderboard,
        {},
        {},
    )
    cross = {"identities": {"2000000010": {}}}
    feeds = {str(GAME): {"physical_pitches": 3, "nonpitch_at_bats": []}}
    result = finish(reviewed, cross, feeds, {}, "a" * 64)
    assert result["status"] == "PACKAGE_A_SYNTHETIC_PASS_NOT_APPLIED"
    assert clean_coverage(result["leaderboard_coverage"])
    assert result["production_write_allowed"] is False
    leaderboard["missing_values"].append([2000000010, "fg", "ALL", "fip"])
    with pytest.raises(ReleaseError, match="coverage"):
        finish(reviewed, cross, feeds, {}, "a" * 64)
    reviewed[0]["synthetic"] = False
    result = finish(reviewed, cross, feeds, {}, "a" * 64)
    assert result["status"] == "PACKAGE_A_EVIDENCE_REVIEW_REQUIRED"
    assert not clean_coverage(result["leaderboard_coverage"])
