"""Correction plan, aggregate and transaction safety tests."""

from copy import deepcopy

import pytest

from scripts.apply_future_corrections import expected_patches, validate_totals
from scripts.reconcile_future_sources import plan_all, synthetic_bundle
from scripts.rehearse_snapshot_release import ReleaseError


def fixture():
    bundle = synthetic_bundle()
    packet = bundle["pitchers"][0]
    staged = {
        packet["pitcher_id"]: {
            f"{row['game_pk']}_{row['at_bat_number']}_{row['pitch_number']}": dict(row)
            for row in packet["detail"]
        }
    }
    report = {
        "season": 2027,
        "synthetic": True,
        "source_manifest": {"date_from": "2027-04-01", "date_to": "2027-04-02"},
    }
    return staged, plan_all(report, staged, bundle)


def test_expected_patches_and_aggregate_validation():
    staged, plan = fixture()
    patches = expected_patches(staged, plan)
    assert len(patches) == 6
    validate_totals(patches, plan)
    assert sum(row[3] or 0 for row in patches.values()) == 2


@pytest.mark.parametrize("failure", ["extra_field", "duplicate", "missing", "unknown_key"])
def test_reject_invalid_patch_scope(failure):
    staged, plan = fixture()
    broken = deepcopy(plan)
    if failure == "extra_field":
        broken["patches"][0]["pitch_type"] = "SI"
    elif failure == "duplicate":
        broken["patches"].append(broken["patches"][0])
    elif failure == "missing":
        broken["patches"].pop()
    else:
        broken["patches"][0]["pitch_id"] = "1_1_1"
    with pytest.raises(ReleaseError):
        expected_patches(staged, broken)


@pytest.mark.parametrize("field", ["rv", "numerator", "denominator"])
def test_reject_incorrect_post_correction_aggregates(field):
    staged, plan = fixture()
    patches = expected_patches(staged, plan)
    key = next(key for key, row in patches.items() if row[3] == 1)
    owner, rv, numerator, denom = patches[key]
    if field == "rv":
        rv += 0.1
    elif field == "numerator":
        numerator += 0.1
    else:
        denom = 0
    patches[key] = (owner, rv, numerator, denom)
    with pytest.raises(ReleaseError):
        validate_totals(patches, plan)
