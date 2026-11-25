"""Archive regular-season Savant responses and reproduce reviewed correction evidence."""

from __future__ import annotations

import argparse
import csv
import io
import json
import time
from datetime import datetime, timezone
from math import isfinite
from pathlib import Path
from urllib.parse import urlencode
from urllib.request import Request, urlopen

from scripts.reconcile_future_sources import plan_all, read_staged_sources, synthetic_bundle
from scripts.rehearse_snapshot_release import ReleaseError, evidence, require, save, sha

ORIGIN = "https://baseballsavant.mlb.com"
MAX_BYTES = 32 * 1024 * 1024
DETAIL_FIELDS = (
    "game_pk",
    "at_bat_number",
    "pitch_number",
    "pitcher",
    "batter",
    "game_date",
    "game_type",
    "game_year",
    "pitch_type",
    "description",
    "events",
    "stand",
    "p_throws",
    "delta_run_exp",
)
INT_FIELDS = ("game_pk", "at_bat_number", "pitch_number", "pitcher", "batter", "game_year")


def query_specs(pitcher, season, first, last):
    params = {
        "player_type": "pitcher",
        "pitchers_lookup[]": pitcher,
        "hfSea": f"{season}|",
        "hfGT": "R|",
        "game_date_gt": first,
        "game_date_lt": last,
        "min_pitches": 0,
        "min_results": 0,
    }
    woba = {**params, "hfFlag": "is_pa|", "outputFormat": "json", "chk_stats_woba": "on"}
    return {
        "detail": (
            "/statcast_search/csv",
            {**params, "type": "details", "all": "true"},
        ),
        "rv_aggregate": (
            "/statcast_search",
            {
                **params,
                "group_by": "name",
                "outputFormat": "json",
                "chk_stats_delev_pitcher_run_exp": "on",
                "chk_stats_delev_pitcher_run_value_per_100": "on",
            },
        ),
        "woba_detail": ("/statcast_search", {**woba, "group_by": "name-event"}),
        "woba_aggregate": ("/statcast_search", {**woba, "group_by": "name"}),
    }


def timestamp():
    return datetime.now(timezone.utc).isoformat()


def download(url):
    request = Request(
        url,
        headers={"User-Agent": "MLB-Pitch-Intelligence/1.0", "Accept": "application/json,text/csv"},
    )
    with urlopen(request, timeout=45) as response:
        require(response.status == 200 and response.geturl() == url, "Unexpected HTTP response.")
        data = response.read(MAX_BYTES + 1)
        require(0 < len(data) <= MAX_BYTES, "Empty or oversized Savant response.")
        return data, response.status, response.headers.get("Content-Type", "")


def synthetic_download(kind):
    packet = synthetic_bundle()["pitchers"][0]
    if kind == "detail":
        output = io.StringIO()
        writer = csv.DictWriter(output, fieldnames=DETAIL_FIELDS)
        writer.writeheader()
        for row in packet[kind]:
            writer.writerow({**row, "game_year": 2027})
        return output.getvalue().encode("utf-8"), 200, "text/csv"
    return json.dumps(packet[kind], allow_nan=False).encode("utf-8"), 200, "application/json"


def archive_response(raw, pitcher, kind, spec, synthetic, fetch):
    path, params = spec
    url = ORIGIN + path + "?" + urlencode(params)
    started = timestamp()
    if synthetic:
        data, status, content_type = synthetic_download(kind)
    else:
        data, status, content_type = fetch(url)
    require(status == 200 and 0 < len(data) <= MAX_BYTES, "Invalid response.")
    suffix = "csv" if kind == "detail" else "json"
    name = f"{pitcher}_{kind}.{suffix}"
    destination = raw / name
    with destination.open("xb") as handle:
        handle.write(data)
    record = {
        "pitcher_id": pitcher,
        "kind": kind,
        "file": name,
        "url": url,
        "parameters": params,
        "started_utc": started,
        "received_utc": timestamp(),
        "http_status": status,
        "content_type": content_type,
        "synthetic": synthetic,
        **evidence(destination),
    }
    save(raw / f"{name}.meta.json", record)
    return record


def parse_detail(data, pitcher, season):
    reader = csv.DictReader(io.StringIO(data.decode("utf-8-sig"), newline=""))
    header = reader.fieldnames or []
    require(
        len(header) == len(set(header)) and set(DETAIL_FIELDS).issubset(header),
        "Savant detail header missing fields or contains duplicates.",
    )
    rows = []
    for original in reader:
        require(
            None not in original and all(value is not None for value in original.values()),
            "Malformed Savant CSV row.",
        )
        row = {field: original[field] for field in DETAIL_FIELDS}
        for field in INT_FIELDS:
            require(row[field].isdigit(), "Noninteger detail identity or season.")
            row[field] = int(row[field])
        require(
            row["pitcher"] == pitcher
            and row["game_year"] == season
            and row["game_type"] == "R",
            "Savant returned an incorrect pitcher, season or game type.",
        )
        raw_value = row["delta_run_exp"]
        value = float(raw_value) if raw_value.strip() else None
        require(value is None or isfinite(value), "Nonfinite source run value.")
        row["delta_run_exp"] = value
        rows.append(row)
    require(0 < len(rows) < 30000, "Empty or potentially truncated detail response.")
    return rows


def parse_json(data):
    def reject_constant(value):
        raise ReleaseError(f"Nonfinite JSON constant: {value}")

    def unique_pairs(pairs):
        result = {}
        for key, value in pairs:
            require(key not in result, "Duplicate JSON object key.")
            result[key] = value
        return result

    result = json.loads(data, parse_constant=reject_constant, object_pairs_hook=unique_pairs)
    require(
        isinstance(result, list) and all(isinstance(row, dict) for row in result),
        "Expected Savant JSON record array.",
    )
    return result


def build_bundle(report, staged, raw, records, staging_sha):
    manifest = report["source_manifest"]
    season = report["season"]
    first, last = manifest["date_from"], manifest["date_to"]
    synthetic = report["synthetic"]
    lookup = {}
    for record in records:
        key = record["pitcher_id"], record["kind"]
        require(key not in lookup, "Duplicate archived response.")
        lookup[key] = record
    packets = []
    for pitcher in sorted(staged):
        packet = {"pitcher_id": pitcher, "season": season}
        for kind, (path, params) in query_specs(pitcher, season, first, last).items():
            record = lookup.pop((pitcher, kind), None)
            require(record is not None, "Missing archived response.")
            suffix = "csv" if kind == "detail" else "json"
            name = f"{pitcher}_{kind}.{suffix}"
            require(
                record["file"] == name
                and record["url"] == ORIGIN + path + "?" + urlencode(params)
                and record["parameters"] == params
                and record["synthetic"] is synthetic
                and record["http_status"] == 200,
                "Archived response provenance mismatch.",
            )
            started = datetime.fromisoformat(record["started_utc"])
            received = datetime.fromisoformat(record["received_utc"])
            require(
                started.utcoffset() is not None
                and received.utcoffset() is not None
                and received >= started,
                "Invalid response timestamps.",
            )
            destination = raw / name
            require(
                evidence(destination) == {k: record[k] for k in ("bytes", "sha256")}
                and json.loads((raw / f"{name}.meta.json").read_bytes()) == record,
                "Archived response or metadata changed.",
            )
            data = destination.read_bytes()
            require(
                0 < len(data) <= MAX_BYTES
                and evidence(destination) == {k: record[k] for k in ("bytes", "sha256")},
                "Archived response changed during replay.",
            )
            packet[kind] = (
                parse_detail(data, pitcher, season) if kind == "detail" else parse_json(data)
            )
            if kind.endswith("_aggregate"):
                for row in packet[kind]:
                    if "pitcher" in row:
                        require(row["pitcher"] == pitcher, "Wrong aggregate pitcher.")
                    if "game_year" in row:
                        require(row["game_year"] == season, "Wrong aggregate season.")
        packets.append(packet)
    require(not lookup, "Extra archived response.")
    bundle = {
        "schema": 1,
        "season": season,
        "synthetic": synthetic,
        "date_from": first,
        "date_to": last,
        "game_type": "R",
        "rv_method": "context_neutral",
        "pitchers": packets,
        "acquisition": {
            "schema": 1,
            "staging_report_sha256": staging_sha,
            "responses": records,
        },
    }
    return bundle, plan_all(report, staged, bundle)


def replay_bundle(report, staged, bundle_path, staging_sha, bundle):
    acquisition = bundle["acquisition"]
    require(
        acquisition["schema"] == 1 and acquisition["staging_report_sha256"] == staging_sha,
        "Evidence is not bound to the approved staging report.",
    )
    rebuilt, plan = build_bundle(
        report, staged, bundle_path.parent / "raw", acquisition["responses"], staging_sha
    )
    require(rebuilt == bundle, "Normalized evidence differs from archived raw responses.")
    require(
        plan["status"] == "RECONCILIATION_PLAN_PASS_NOT_APPLIED",
        "Evidence requires restaging; correction plan blocked.",
    )
    return plan


def acquire(report, staged, output, staging_sha, *, fetch=download, delay=0.25):
    output.mkdir(parents=True, exist_ok=False)
    raw = output / "raw"
    raw.mkdir()
    manifest = report["source_manifest"]
    season = report["season"]
    records = []
    for pitcher in sorted(staged):
        specs = query_specs(pitcher, season, manifest["date_from"], manifest["date_to"])
        for kind, spec in specs.items():
            records.append(archive_response(raw, pitcher, kind, spec, report["synthetic"], fetch))
            if not report["synthetic"]:
                time.sleep(delay)
        print(f"Archived four responses: {pitcher}", flush=True)
    bundle, plan = build_bundle(report, staged, raw, records, staging_sha)
    if plan["revisions"]:
        save(output / "restage_required.json", plan)
        raise ReleaseError("Source revisions require restaging; no approved bundle generated.")
    save(output / "evidence_bundle.json", bundle)
    return bundle, plan


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--staging-report", type=Path, required=True)
    parser.add_argument("--staging-sha", required=True)
    parser.add_argument("--synthetic", action="store_true")
    parser.add_argument("--output", type=Path)
    parser.add_argument("--verify-bundle", type=Path)
    parser.add_argument("--bundle-sha")
    args = parser.parse_args()
    try:
        require(bool(args.output) != bool(args.verify_bundle), "Choose acquire or verify.")
        report, staged = read_staged_sources(args.staging_report, args.staging_sha)
        require(report["synthetic"] is args.synthetic, "Synthetic/real mode mismatch.")
        if args.verify_bundle:
            require(
                args.bundle_sha and sha(args.verify_bundle) == args.bundle_sha,
                "Bundle checksum mismatch.",
            )
            bundle = json.loads(args.verify_bundle.read_bytes())
            plan = replay_bundle(report, staged, args.verify_bundle, args.staging_sha, bundle)
            require(sha(args.verify_bundle) == args.bundle_sha, "Bundle changed during replay.")
            path = args.verify_bundle
        else:
            require(not args.bundle_sha, "Bundle checksum only applies to verification.")
            bundle, plan = acquire(report, staged, args.output, args.staging_sha)
            path = args.output / "evidence_bundle.json"
        require(sha(args.staging_report) == args.staging_sha, "Staging report changed.")
        print(f"Pitchers: {plan['pitchers']}; pitches: {plan['pitches']}; PA: {plan['official_pa']}")
        print(f"Archived responses: {len(bundle['acquisition']['responses'])}")
        print(f"Bundle SHA-256: {sha(path)}")
        print("SAVANT_EVIDENCE_PASS_NOT_APPLIED")
        print("No database writes or publication performed.")
        return 0
    except Exception as exc:
        message = str(exc) if isinstance(exc, (ReleaseError, ValueError)) else type(exc).__name__
        print("SAVANT_EVIDENCE_FAILED:", message)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
