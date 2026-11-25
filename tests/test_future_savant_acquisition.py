"""Raw Savant acquisition and replay tests without any network or database access."""

import json

import pytest

from scripts.acquire_future_savant import (
    acquire,
    parse_detail,
    parse_json,
    query_specs,
    replay_bundle,
    synthetic_download,
)
from scripts.reconcile_future_sources import synthetic_bundle
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
    return report, staged


def test_archive_replay_and_exact_regular_season_queries(tmp_path):
    report, staged = fixture()

    def no_network(url):
        pytest.fail("Synthetic acquisition attempted network access.")

    output = tmp_path / "archive"
    bundle, plan = acquire(report, staged, output, "a" * 64, fetch=no_network)
    assert plan["pitches"] == 6 and plan["official_pa"] == 2
    assert len(bundle["acquisition"]["responses"]) == 4
    assert len(list((output / "raw").iterdir())) == 8
    for record in bundle["acquisition"]["responses"]:
        assert record["parameters"]["hfGT"] == "R|"
        assert record["parameters"]["hfSea"] == "2027|"
    assert replay_bundle(
        report, staged, output / "evidence_bundle.json", "a" * 64, bundle
    ) == plan


@pytest.mark.parametrize("failure", ["raw", "metadata", "query", "bundle", "stage"])
def test_replay_rejects_tampering(tmp_path, failure):
    report, staged = fixture()
    output = tmp_path / "archive"
    bundle, _ = acquire(report, staged, output, "a" * 64)
    record = bundle["acquisition"]["responses"][0]
    raw = output / "raw" / record["file"]
    digest = "a" * 64
    if failure == "raw":
        raw.write_bytes(raw.read_bytes() + b"\n")
    elif failure == "metadata":
        (output / "raw" / f"{record['file']}.meta.json").write_text("{}", encoding="utf-8")
    elif failure == "query":
        record["parameters"]["hfGT"] = "S|"
    elif failure == "bundle":
        bundle["pitchers"][0]["detail"][0]["delta_run_exp"] = 0.123
    else:
        digest = "b" * 64
    with pytest.raises(ReleaseError):
        replay_bundle(report, staged, output / "evidence_bundle.json", digest, bundle)


def test_real_mode_uses_four_separate_queries_and_preserves_response(tmp_path):
    report, staged = fixture()
    report["synthetic"] = False
    pitcher = next(iter(staged))
    specs = query_specs(pitcher, 2027, "2027-04-01", "2027-04-02")
    from urllib.parse import urlencode

    responses = {
        path + "?" + urlencode(params): kind for kind, (path, params) in specs.items()
    }
    calls = []

    def fake_fetch(url):
        calls.append(url)
        return synthetic_download(responses[url.removeprefix("https://baseballsavant.mlb.com")])

    bundle, plan = acquire(
        report, staged, tmp_path / "archive", "a" * 64, fetch=fake_fetch, delay=0
    )
    assert len(calls) == len(set(calls)) == 4
    assert bundle["synthetic"] is False
    assert plan["status"] == "RECONCILIATION_PLAN_PASS_NOT_APPLIED"


@pytest.mark.parametrize("replacement", [b"2026", b"2027.0", b"2027x"])
def test_wrong_or_invalid_season_is_rejected(replacement):
    raw, _, _ = synthetic_download("detail")
    raw = raw.replace(b",2027,", b"," + replacement + b",", 1)
    with pytest.raises(ReleaseError):
        parse_detail(raw, 2000000010, 2027)


def test_malformed_json_and_duplicate_keys_fail_closed():
    for raw in (b'{"a": 1}', b'[{"a": 1, "a": 2}]', b'[{"a": NaN}]'):
        with pytest.raises(ReleaseError):
            parse_json(raw)


def test_bad_aggregate_does_not_emit_approved_bundle(tmp_path):
    report, staged = fixture()
    report["synthetic"] = False
    pitcher = next(iter(staged))
    specs = query_specs(pitcher, 2027, "2027-04-01", "2027-04-02")
    from urllib.parse import urlencode

    responses = {
        path + "?" + urlencode(params): kind for kind, (path, params) in specs.items()
    }

    def fetch(url):
        kind = responses[url.removeprefix("https://baseballsavant.mlb.com")]
        if kind == "rv_aggregate":
            return json.dumps([{"pitches": 6, "delev_pitcher_run_exp": 99}]).encode(), 200, ""
        return synthetic_download(kind)

    output = tmp_path / "archive"
    with pytest.raises(ValueError):
        acquire(report, staged, output, "a" * 64, fetch=fetch, delay=0)
    assert not (output / "evidence_bundle.json").exists()
    assert len(list((output / "raw").iterdir())) == 8
