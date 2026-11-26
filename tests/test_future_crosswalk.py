"""Independent register coverage, identity conflict and replay tests."""

import pytest

from scripts.acquire_future_crosswalk import (
    acquire,
    build_evidence,
    fixtures,
    planned_mapping,
    urls,
    verify_register,
)
from scripts.rehearse_snapshot_release import ReleaseError

PID = 2000000010
EXPECTED = {PID: "9000001"}


def test_acquire_and_replay(tmp_path):
    def no_network(url):
        pytest.fail("Synthetic evidence must not access network")

    output = tmp_path / "crosswalk"
    result = acquire(output, "synthetic", True, EXPECTED, 2027, {}, fetch=no_network)
    assert result["identities"][str(PID)]["fangraphs_id"] == "9000001"
    assert len(result["responses"]) == 16
    assert (
        build_evidence(output / "raw", result["responses"], "synthetic", True, EXPECTED, 2027, {})
        == result
    )
    (output / "raw" / "people-f.csv").write_bytes(b"changed")
    with pytest.raises(ReleaseError, match="checksum"):
        build_evidence(output / "raw", result["responses"], "synthetic", True, EXPECTED, 2027, {})


@pytest.mark.parametrize(
    "failure", ["missing_shard", "missing_id", "wrong_fg", "wrong_mlb", "duplicate"]
)
def test_reject_bad_register(failure):
    bodies = fixtures()
    if failure == "missing_shard":
        bodies.pop("people-f.csv")
    elif failure == "missing_id":
        bodies["people-0.csv"] = bodies["people-f.csv"]
    elif failure == "wrong_fg":
        bodies["people-0.csv"] = bodies["people-0.csv"].replace(b"9000001", b"9000002")
    elif failure == "wrong_mlb":
        bodies["people-0.csv"] = bodies["people-0.csv"].replace(b"2000000010", b"2000000012")
    else:
        bodies["people-f.csv"] = bodies["people-0.csv"]
    with pytest.raises(ReleaseError):
        verify_register(bodies, EXPECTED)


def test_immutable_register_revision():
    with pytest.raises(ReleaseError, match="immutable"):
        urls("master", False)
    assert len(urls("a" * 40, False)) == 16


def test_mapping_requires_mlb_people():
    leaderboard = {
        "fangraphs_stuff": [{"mlb_id": PID, "fangraphs_id": "9000001"}],
        "published_pitching_metrics": [],
    }
    assert planned_mapping(leaderboard, {str(PID): {}}) == EXPECTED
    with pytest.raises(ReleaseError, match="MLB people"):
        planned_mapping(leaderboard, {})
