"""Offline reconciliation tests with independent synthetic expectations."""

from copy import deepcopy

import pytest

from scripts.reconcile_future_sources import plan_all, synthetic_bundle
from scripts.rehearse_snapshot_release import ReleaseError


def fixture():
    bundle = synthetic_bundle()
    packet = bundle["pitchers"][0]
    pitcher = packet["pitcher_id"]
    staged = {
        pitcher: {
            f"{row['game_pk']}_{row['at_bat_number']}_{row['pitch_number']}": dict(row)
            for row in packet["detail"]
        }
    }
    report = {
        "season": 2027,
        "synthetic": True,
        "source_manifest": {"date_from": "2027-04-01", "date_to": "2027-04-02"},
    }
    return report, staged, bundle


def test_complete_neutral_rv_and_woba_plan():
    report, staged, bundle = fixture()
    result = plan_all(report, staged, bundle)
    assert result["status"] == "RECONCILIATION_PLAN_PASS_NOT_APPLIED"
    assert result["pitches"] == 6
    assert result["official_pa"] == 2
    assert len(result["patches"]) == 6
    assert sum(p["savant_woba_denominator"] or 0 for p in result["patches"]) == 2
    assert sum(p["delta_run_expectancy"] for p in result["patches"]) == pytest.approx(0.6)
    assert result["production_write_allowed"] is False


def test_classification_and_outcome_changes_require_full_restage():
    report, staged, bundle = fixture()
    changed = deepcopy(bundle)
    changed["pitchers"][0]["detail"][0]["pitch_type"] = "SI"
    result = plan_all(report, staged, changed)
    assert result["status"] == "RESTAGE_REQUIRED_NO_PATCHES"
    assert len(result["revisions"]) == 1
    assert not result["patches"]


@pytest.mark.parametrize("failure", ["missing", "extra", "rv", "woba", "wrong_game", "null_rv"])
def test_reject_incomplete_or_invalid_official_evidence(failure):
    report, staged, bundle = fixture()
    packet = bundle["pitchers"][0]
    if failure == "missing":
        packet["detail"].pop()
    elif failure == "extra":
        packet["detail"].append(dict(packet["detail"][0]))
    elif failure == "rv":
        packet["rv_aggregate"][0]["delev_pitcher_run_exp"] = 0
    elif failure == "woba":
        packet["woba_aggregate"][0]["woba"] = 0
    elif failure == "wrong_game":
        packet["detail"][0]["game_type"] = "S"
    else:
        packet["detail"][0]["delta_run_exp"] = None
    with pytest.raises((ReleaseError, ValueError)):
        plan_all(report, staged, bundle)
