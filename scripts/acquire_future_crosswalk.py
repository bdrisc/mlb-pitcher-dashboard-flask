"""Verify planned FanGraphs identities against a pinned Chadwick register snapshot."""

from __future__ import annotations

import argparse
import csv
import io
import json
import re
from pathlib import Path

from scripts.acquire_future_leaderboards import build_report, digest, validate_correction
from scripts.acquire_future_mlb_scope import rebuild
from scripts.acquire_future_savant import MAX_BYTES, download, timestamp
from scripts.apply_future_leaderboards import mappings
from scripts.reconcile_future_sources import read_staged_sources
from scripts.rehearse_snapshot_release import require, save, sha

ORIGIN = "https://raw.githubusercontent.com/chadwickbureau/register"
SHARDS = tuple(f"people-{key}.csv" for key in "0123456789abcdef")
FIELDS = {"key_person", "key_mlbam", "key_fangraphs"}
FIXTURE_COMMIT = "synthetic"


def urls(revision, synthetic):
    require(
        revision == FIXTURE_COMMIT if synthetic else bool(re.fullmatch(r"[0-9a-f]{40}", revision)),
        "Require an immutable Chadwick commit or the synthetic fixture.",
    )
    return {name: f"{ORIGIN}/{revision}/data/{name}" for name in SHARDS}


def planned_mapping(leaderboard, people):
    pairs = [
        (row["mlb_id"], row["fangraphs_id"])
        for table in ("fangraphs_stuff", "published_pitching_metrics")
        for row in leaderboard[table]
        if row["fangraphs_id"] is not None
    ]
    result = mappings(pairs)
    require(bool(result), "No planned FanGraphs identities to verify.")
    require(
        all(str(pid) in people for pid in result),
        "Planned identity missing from approved MLB people.",
    )
    return result


def verify_register(bodies, expected):
    require(set(bodies) == set(SHARDS), "Incomplete Chadwick register shard population.")
    wanted_fg = {fg: pid for pid, fg in expected.items()}
    found = {}
    row_counts = {}
    for name in SHARDS:
        reader = csv.DictReader(io.StringIO(bodies[name].decode("utf-8-sig"), newline=""))
        header = reader.fieldnames or []
        require(FIELDS <= set(header) and len(header) == len(set(header)), "Bad register header.")
        count = 0
        for row in reader:
            require(
                None not in row and all(v is not None for v in row.values()),
                "Malformed register row.",
            )
            count += 1
            raw_mlb = row["key_mlbam"].strip()
            raw_fg = row["key_fangraphs"].strip()
            pid = int(raw_mlb) if raw_mlb.isdigit() else None
            fg = str(int(raw_fg)) if raw_fg.isdigit() else raw_fg
            if pid not in expected and fg not in wanted_fg:
                continue
            require(
                pid in expected and expected[pid] == fg and wanted_fg.get(fg) == pid,
                "Conflicting or incomplete independent player mapping.",
            )
            require(pid not in found, "Duplicate independent player mapping.")
            key = row["key_person"].strip()
            require(bool(key), "Missing Chadwick person key.")
            found[pid] = {"fangraphs_id": fg, "key_person": key, "shard": name}
        row_counts[name] = count
    require(set(found) == set(expected), "Missing independent player mapping.")
    require(
        len({v["key_person"] for v in found.values()}) == len(found),
        "Duplicate Chadwick person key.",
    )
    return {str(pid): found[pid] for pid in sorted(found)}, row_counts


def fixtures():
    header = b"key_person,key_mlbam,key_fangraphs\n"
    result = dict.fromkeys(SHARDS, header)
    result["people-0.csv"] += b"fixture-pitcher,2000000010,9000001\n"
    return result


def approved_inputs(args):
    stage, staged = read_staged_sources(args.staging_report, args.staging_sha)
    require(stage["synthetic"] is args.synthetic, "Synthetic/real mode mismatch.")
    validate_correction(
        args.correction_report, args.correction_sha, stage, staged, args.staging_sha
    )
    require(sha(args.leaderboard) == args.leaderboard_sha, "Leaderboard checksum mismatch.")
    leaderboard = json.loads(args.leaderboard.read_bytes())
    require(
        leaderboard
        == build_report(
            stage,
            staged,
            args.leaderboard.parent / "raw",
            leaderboard["responses"],
            args.staging_sha,
            args.correction_sha,
        ),
        "Leaderboard evidence replay differs.",
    )
    require(sha(args.scope) == args.scope_sha, "MLB scope checksum mismatch.")
    scope = json.loads(args.scope.read_bytes())
    require(
        scope
        == rebuild(
            stage,
            staged,
            args.scope.parent / "raw",
            scope["responses"],
            args.staging_sha,
            scope["window"]["start"],
            scope["window"]["end"],
        ),
        "MLB scope evidence replay differs.",
    )
    expected = planned_mapping(leaderboard, scope["people"])
    return expected, stage["season"]


def build_evidence(raw, records, revision, synthetic, expected, season, bindings):
    sources = urls(revision, synthetic)
    require(set(records) == set(sources), "Missing register response.")
    bodies = {}
    for name, url in sources.items():
        record = records[name]
        require(
            record["url"] == url
            and record["file"] == name
            and record["synthetic"] is synthetic
            and record["http_status"] == 200
            and json.loads((raw / f"{name}.meta.json").read_bytes()) == record,
            "Register source provenance mismatch.",
        )
        data = (raw / name).read_bytes()
        require(
            0 < len(data) <= MAX_BYTES
            and len(data) == record["bytes"]
            and digest(data) == record["sha256"],
            "Register archive checksum mismatch.",
        )
        bodies[name] = data
    identities, counts = verify_register(bodies, expected)
    require(synthetic or all(counts.values()), "Empty real register shard.")
    return {
        "schema": 1,
        "status": "CROSSWALK_EVIDENCE_PASS_NOT_APPLIED",
        "season": season,
        "synthetic": synthetic,
        "register_commit": revision,
        "input_sha256": bindings,
        "identities": identities,
        "shard_rows": counts,
        "responses": records,
        "production_write_allowed": False,
        "coverage_review_required": True,
    }


def acquire(output, revision, synthetic, expected, season, bindings, fetch=download):
    sources = urls(revision, synthetic)
    output.mkdir(parents=True, exist_ok=False)
    raw = output / "raw"
    raw.mkdir()
    records = {}
    fixture = fixtures() if synthetic else None
    for name, url in sources.items():
        started = timestamp()
        data, status, content_type = (
            (fixture[name], 200, "text/csv") if fixture is not None else fetch(url)
        )
        require(status == 200 and 0 < len(data) <= MAX_BYTES, "Invalid register response.")
        with (raw / name).open("xb") as handle:
            handle.write(data)
        record = dict(
            file=name,
            url=url,
            started_utc=started,
            received_utc=timestamp(),
            http_status=status,
            content_type=content_type,
            synthetic=synthetic,
            bytes=len(data),
            sha256=digest(data),
        )
        save(raw / f"{name}.meta.json", record)
        records[name] = record
        print(f"Archived {name}", flush=True)
    result = build_evidence(raw, records, revision, synthetic, expected, season, bindings)
    save(output / "crosswalk_evidence.json", result)
    return result


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    for name in ("staging-report", "correction-report", "leaderboard", "scope"):
        parser.add_argument("--" + name, required=True, type=Path)
    for name in ("staging-sha", "correction-sha", "leaderboard-sha", "scope-sha"):
        parser.add_argument("--" + name, required=True)
    parser.add_argument("--register-commit")
    parser.add_argument("--synthetic", action="store_true")
    parser.add_argument("--output", type=Path)
    parser.add_argument("--verify-report", type=Path)
    parser.add_argument("--report-sha")
    args = parser.parse_args()
    try:
        require(bool(args.output) != bool(args.verify_report), "Choose acquisition or replay.")
        require(
            bool(args.register_commit) != args.synthetic,
            "Specify a real register commit or use the synthetic fixture.",
        )
        revision = FIXTURE_COMMIT if args.synthetic else args.register_commit
        expected, season = approved_inputs(args)
        bindings = {
            "staging": args.staging_sha,
            "correction": args.correction_sha,
            "leaderboard": args.leaderboard_sha,
            "scope": args.scope_sha,
        }
        if args.verify_report:
            path = args.verify_report
            require(sha(path) == args.report_sha, "Crosswalk report checksum mismatch.")
            result = json.loads(path.read_bytes())
            rebuilt = build_evidence(
                path.parent / "raw",
                result["responses"],
                revision,
                args.synthetic,
                expected,
                season,
                bindings,
            )
            require(result == rebuilt and sha(path) == args.report_sha, "Replay differs.")
        else:
            require(not args.report_sha, "Report checksum applies only to replay.")
            result = acquire(args.output, revision, args.synthetic, expected, season, bindings)
            path = args.output / "crosswalk_evidence.json"
        require(
            approved_inputs(args) == (expected, season),
            "Approved input evidence changed.",
        )
        print(f"Verified mappings: {len(result['identities'])}")
        print(f"Archived register shards: {len(result['responses'])}")
        print(f"Report SHA-256: {sha(path)}")
        print(result["status"])
        print("No database writes or publication performed.")
        return 0
    except Exception as exc:
        print("CROSSWALK_FAILED:", str(exc) if isinstance(exc, ValueError) else type(exc).__name__)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
