"""Package A game-feed completeness and coverage regression checks."""

from copy import deepcopy

import pytest

from scripts import acquire_future_leaderboards as leaderboards
from scripts import acquire_future_mlb_scope as mlb_scope
from scripts import acquire_future_savant as savant
from scripts import future_game_feed as feed
from scripts import snapshot_integrity as integrity
from scripts.reconcile_future_sources import read_json, read_staged_sources
from scripts.rehearse_snapshot_release import ReleaseError, save, sha
from scripts.stage_future_ingestion import synthetic_sources
from scripts.validate_future_release_evidence import (
    SYNTHETIC_FILES,
    clean_coverage,
    finish,
    run,
    synthetic_inputs,
)

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


def test_complete_package_a_fixture(tmp_path):
    paths = {name: tmp_path / path for name, path in SYNTHETIC_FILES.items()}
    sources = paths["staging"].parent / "sources"
    sources.mkdir(parents=True)
    _, _, manifest_path, _ = synthetic_sources(sources)
    manifest = read_json(manifest_path)
    historical = {"tables": {"fixture": {"rows": 1, "sha256": "sealed"}}}
    stage = {
        "schema": 1,
        "status": "STAGING_PASS_QUARANTINED",
        "synthetic": True,
        "season": 2027,
        "source_manifest": manifest,
        "source_values_matched": manifest["rows"],
        "historical_fingerprint": historical,
        "production_write_allowed": False,
    }
    save(paths["staging"], stage)
    stage_sha = sha(paths["staging"])
    _, staged_rows = read_staged_sources(paths["staging"], stage_sha)
    _, plan = savant.acquire(stage, staged_rows, paths["savant"].parent, stage_sha)
    save(
        paths["plan"],
        {**plan, "staging_report_sha256": stage_sha, "bundle_evidence": None},
    )
    before = {t: {"rows": 1, "sha256": "before"} for t in integrity.TABLES}
    correction = {
        "schema": 1,
        "status": "CORRECTIONS_PASS_QUARANTINED",
        "synthetic": True,
        "season": 2027,
        "production_write_allowed": False,
        "staging_report_sha256": stage_sha,
        "plan_sha256": sha(paths["plan"]),
        "historical_fingerprint": historical,
        "patched_pitches": plan["pitches"],
        "official_pa": plan["official_pa"],
        "pitcher_results": plan["pitcher_results"],
        "candidate_database": "mlb_release_candidate_fixture",
        "candidate_fingerprint": before,
    }
    paths["correction"].parent.mkdir()
    save(paths["correction"], correction)
    correction_sha = sha(paths["correction"])
    leaderboard = leaderboards.acquire(
        stage, staged_rows, paths["leaderboard"].parent, stage_sha, correction_sha
    )
    mlb_scope.acquire(
        stage, staged_rows, paths["scope"].parent, stage_sha, "2027-04-01", "2027-04-02"
    )
    counts = {
        t: len(leaderboard[t])
        for t in ("fangraphs_stuff", "published_pitching_metrics", "savant_active_spin")
    }
    after = {
        t: {"rows": v["rows"] + counts[t], "sha256": "after"} if t in counts else v
        for t, v in before.items()
    }
    paths["import"].parent.mkdir()
    save(
        paths["import"],
        {
            "schema": 1,
            "status": "LEADERBOARD_IMPORT_PASS_QUARANTINED",
            "synthetic": True,
            "season": 2027,
            "production_write_allowed": False,
            "staging_report_sha256": stage_sha,
            "correction_report_sha256": correction_sha,
            "leaderboard_report_sha256": sha(paths["leaderboard"]),
            "source_database": correction["candidate_database"],
            "source_fingerprint": before,
            "candidate_fingerprint": after,
            "historical_fingerprint": historical,
            "inserted_rows": counts,
        },
    )
    inputs = synthetic_inputs(tmp_path)
    out = tmp_path / "package_a"
    result = run(inputs, True, "synthetic", output=out)
    assert result["physical_pitches"] == 6
    assert result["completed_games"] == 2
    assert result["crosswalk_mappings"] == 1
    assert result["status"] == "PACKAGE_A_SYNTHETIC_PASS_NOT_APPLIED"
    report = out / "package_a_report.json"
    assert (
        run(inputs, True, "synthetic", verify_report=report, report_sha=sha(report))
        == result
    )
    paths["scope"].write_text("changed", encoding="utf-8")
    with pytest.raises(ReleaseError, match="Input checksum mismatch"):
        run(inputs, True, "synthetic", verify_report=report, report_sha=sha(report))
