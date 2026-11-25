"""Read-only leaderboard acquisition, missing data and source replay tests."""

import json

import pytest

from scripts.acquire_future_leaderboards import (
    acquire,
    build_report,
    normalize,
    synthetic_bodies,
)
from scripts.rehearse_snapshot_release import ReleaseError

PID = 2000000010


def staged():
    return {PID: {"1_1_1": {"pitch_type": "FF"}}}


def test_acquire_and_replay(tmp_path):
    report = {"season": 2027, "synthetic": True}

    def no_network(url):
        pytest.fail("Unexpected network access")

    out = tmp_path / "evidence"
    result = acquire(report, staged(), out, "a" * 64, "b" * 64, fetch=no_network)
    assert len(result["fangraphs_stuff"]) == 2
    assert len(result["published_pitching_metrics"]) == 1
    assert result["published_pitching_metrics"][0]["xera"] == 3.1
    assert result["savant_active_spin"][0]["active_spin_pct"] == 95.5
    assert not result["missing_values"]
    assert len(list((out / "raw").iterdir())) == 8
    assert build_report(
        report, staged(), out / "raw", result["responses"], "a" * 64, "b" * 64
    ) == result
    record = result["responses"]["savant_xera"]
    (out / "raw" / record["file"]).write_bytes(b"changed")
    with pytest.raises(ReleaseError, match="checksum"):
        build_report(report, staged(), out / "raw", result["responses"], "a" * 64, "b" * 64)


@pytest.mark.parametrize("failure", ["count", "season", "identity", "duplicate", "nonfinite"])
def test_invalid_fangraphs(failure):
    bodies = synthetic_bodies(2027)
    raw = json.loads(bodies["fangraphs_rates"])
    row = raw["data"][0]
    if failure == "count":
        raw["totalCount"] = 2
    elif failure == "season":
        row["Season"] = 2026
    elif failure == "identity":
        row["playerid"] = 99
    elif failure == "duplicate":
        raw["data"].append(dict(row))
        raw["totalCount"] = 2
    else:
        row["FIP"] = float("inf")
    bodies["fangraphs_rates"] = json.dumps(raw).encode()
    with pytest.raises(ValueError):
        normalize(bodies, 2027, staged())


def test_missing_metrics_are_not_zero_filled():
    bodies = synthetic_bodies(2027)
    raw = json.loads(bodies["fangraphs_rates"])
    raw["data"][0]["SIERA"] = None
    bodies["fangraphs_rates"] = json.dumps(raw).encode()
    result = normalize(bodies, 2027, staged())
    assert result["published_pitching_metrics"][0]["siera"] is None
    assert [PID, "published_rates", "ALL", "siera"] in result["missing_values"]


def test_outside_pitcher_not_planned():
    bodies = synthetic_bodies(2027)
    result = normalize(bodies, 2027, {123: {"1_1_1": {"pitch_type": "FF"}}})
    assert not result["fangraphs_stuff"]
    assert not result["published_pitching_metrics"]
    assert not result["savant_active_spin"]
    assert result["coverage"]["fangraphs_grades"]["outside_staging_pitchers"] == [PID]
    assert result["missing_values"]


def test_invalid_spin_is_rejected():
    bodies = synthetic_bodies(2027)
    bodies["savant_spin"] = bodies["savant_spin"].replace(b"95.5%", b"104.94%")
    with pytest.raises(ReleaseError, match="active-spin"):
        normalize(bodies, 2027, staged())
