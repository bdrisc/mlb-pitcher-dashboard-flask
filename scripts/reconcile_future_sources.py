"""Strict, offline reconciliation of a quarantined future-season source snapshot."""

from __future__ import annotations

import argparse
import csv
import gzip
import json
from collections import defaultdict
from math import isfinite
from pathlib import Path

import pandas as pd

from app.services.pitch_type_refresh import validate_pitch_type_source
from app.services.run_value_refresh import validate_source
from app.services.woba_refresh import NON_PA_EVENTS, verify_woba_outcomes
from scripts.rehearse_snapshot_release import ReleaseError, evidence, require, save, sha


def read_json(path):
    return json.loads(path.read_bytes())


def pitch_key(row):
    fields = ("game_pk", "at_bat_number", "pitch_number")
    values = [row[field] for field in fields]
    require(
        all(type(value) is int and value > 0 for value in values),
        "Invalid source pitch identity.",
    )
    return "_".join(map(str, values))


def read_staged_sources(report_path, digest):
    require(sha(report_path) == digest, "Staging report checksum mismatch.")
    report = read_json(report_path)
    season = report["season"]
    require(
        report["schema"] == 1
        and report["status"] == "STAGING_PASS_QUARANTINED"
        and report["production_write_allowed"] is False
        and type(season) is int
        and season >= 2027,
        "Not a quarantined future-season report.",
    )
    manifest = report["source_manifest"]
    require(manifest["season"] == season, "Staging season mismatch.")
    by_pitcher = defaultdict(dict)
    seen = set()
    for source in manifest["sources"]:
        name = source["file"]
        require(Path(name).name == name, "Invalid staged source filename.")
        path = report_path.parent / "sources" / name
        expected = {field: source[field] for field in ("bytes", "sha256")}
        require(evidence(path) == expected, "Staged source checksum mismatch.")
        opener = gzip.open if path.suffix == ".gz" else open
        count = 0
        with opener(path, "rt", encoding="utf-8-sig", newline="") as handle:
            for row in csv.DictReader(handle):
                for field in ("game_pk", "at_bat_number", "pitch_number", "pitcher", "batter"):
                    row[field] = int(row[field])
                key = pitch_key(row)
                require(key not in seen, "Duplicate staged pitch identity.")
                seen.add(key)
                by_pitcher[row["pitcher"]][key] = row
                count += 1
        require(count == source["rows"], "Staged file count mismatch.")
        require(evidence(path) == expected, "Staged source changed during read.")
    require(
        len(seen) == manifest["rows"] == report["source_values_matched"]
        and len(by_pitcher) == manifest["pitchers"],
        "Staged pitch coverage mismatch.",
    )
    return report, by_pitcher


def plan_pitcher(stored, packet, season, pitcher):
    """Require exact identity coverage and independent neutral-RV / wOBA aggregates."""
    require(
        packet["pitcher_id"] == pitcher and packet["season"] == season,
        "Wrong pitcher-season evidence.",
    )
    detail = packet["detail"]
    keys = {}
    for row in detail:
        key = pitch_key(row)
        require(key not in keys and key in stored, "Duplicate or extra official pitch.")
        original = stored[key]
        require(
            all(
                row[field] == original[field]
                for field in ("game_date", "game_type", "pitcher", "batter")
            )
            and row["game_type"] == "R"
            and row["game_date"].startswith(str(season) + "-"),
            "Official pitch identity or game scope differs.",
        )
        require(
            row["p_throws"] in ("L", "R") and row["stand"] in ("L", "R"),
            "Invalid official handedness.",
        )
        value = row["delta_run_exp"]
        require(
            value is None or (type(value) in (int, float) and isfinite(value)),
            "Invalid neutral RV.",
        )
        require(
            value is not None or row["description"] in ("automatic_ball", "automatic_strike"),
            "Missing physical-pitch neutral RV.",
        )
        keys[key] = row
    require(set(keys) == set(stored), "Official pitch coverage differs from staging.")
    aggregate = packet["rv_aggregate"]
    require(
        len(aggregate) == 1
        and type(aggregate[0]["pitches"]) is int
        and isfinite(aggregate[0]["delev_pitcher_run_exp"]),
        "Invalid official RV aggregate.",
    )
    frame = pd.DataFrame(detail)
    codes = validate_pitch_type_source(frame, pitcher)
    rv = validate_source(frame, aggregate)
    require(set(codes) == set(rv) == set(stored), "Incomplete verified detail.")
    pa_aggregate = packet["woba_aggregate"]
    for row in pa_aggregate:
        require(
            type(row["pa"]) is int
            and row["pa"] >= 0
            and isfinite(row["woba_value"])
            and isfinite(row["woba"]),
            "Invalid official wOBA aggregate.",
        )
    outcomes = verify_woba_outcomes(packet["woba_detail"], pa_aggregate, pitcher, season)
    official_pa = {
        key for key, row in keys.items() if row["events"] and row["events"] not in NON_PA_EVENTS
    }
    require(set(outcomes) == official_pa, "Official PA pitch coverage differs from detail.")
    require(
        all(keys[key]["events"] == outcome[0] for key, outcome in outcomes.items()),
        "Official detail and wOBA event labels differ.",
    )
    revisions = []
    patches = []
    for key in sorted(stored):
        old, new = stored[key], keys[key]
        if codes[key] is None:
            require(
                new["description"] in ("automatic_ball", "automatic_strike"),
                "Physical pitch has no official classification.",
            )
        for field in ("description", "events", "stand", "p_throws", "pitch_type"):
            before = str(old.get(field) or "").strip()
            after = str(new.get(field) or "").strip()
            if field == "pitch_type":
                before = before.upper()
                after = codes[key] or ""
            if before != after:
                revisions.append(
                    {"pitch_id": key, "field": field, "staged": before, "official": after}
                )
        outcome = outcomes.get(key)
        patches.append(
            {
                "pitch_id": key,
                "delta_run_expectancy": rv[key],
                "savant_woba_numerator": outcome[1] if outcome else None,
                "savant_woba_denominator": outcome[2] if outcome else None,
            }
        )
    return {
        "pitcher_id": pitcher,
        "pitches": len(stored),
        "official_pa": len(outcomes),
        "rv_total_pitcher": aggregate[0]["delev_pitcher_run_exp"],
        "woba_numerator": sum(outcome[1] for outcome in outcomes.values()),
        "woba_denominator": sum(outcome[2] for outcome in outcomes.values()),
        "revisions": revisions,
        "patches": patches,
    }


def plan_all(report, staged, bundle):
    manifest = report["source_manifest"]
    require(
        bundle["schema"] == 1
        and bundle["season"] == report["season"]
        and bundle["synthetic"] is report["synthetic"]
        and bundle["date_from"] == manifest["date_from"]
        and bundle["date_to"] == manifest["date_to"]
        and bundle["game_type"] == "R"
        and bundle["rv_method"] == "context_neutral",
        "Evidence scope or provenance mismatch.",
    )
    packets = {}
    for packet in bundle["pitchers"]:
        pitcher = packet["pitcher_id"]
        require(type(pitcher) is int and pitcher not in packets, "Duplicate evidence pitcher.")
        packets[pitcher] = packet
    require(set(packets) == set(staged), "Evidence pitcher coverage differs from staging.")
    results = [
        plan_pitcher(staged[pitcher], packets[pitcher], report["season"], pitcher)
        for pitcher in sorted(staged)
    ]
    revisions = [row for result in results for row in result.pop("revisions")]
    patches = [row for result in results for row in result.pop("patches")]
    return {
        "schema": 1,
        "status": (
            "RESTAGE_REQUIRED_NO_PATCHES" if revisions else "RECONCILIATION_PLAN_PASS_NOT_APPLIED"
        ),
        "season": report["season"],
        "synthetic": report["synthetic"],
        "pitchers": len(results),
        "pitches": sum(row["pitches"] for row in results),
        "official_pa": sum(row["official_pa"] for row in results),
        "pitcher_results": results,
        "revisions": revisions,
        "patches": [] if revisions else patches,
        "production_write_allowed": False,
    }


def synthetic_bundle():
    """Independent fixed expectations for the two-game PR 66 rehearsal."""
    pitcher = 2000000010
    detail = []
    outcomes = []
    for offset in (1, 2):
        for number, description, event, value in (
            (1, "called_strike", "", -0.06),
            (2, "foul_tip", "", -0.07),
            (3, "hit_into_play", "single", 0.43),
        ):
            row = {
                "game_pk": 2000000000 + offset,
                "at_bat_number": 1,
                "pitch_number": number,
                "pitcher": pitcher,
                "batter": 2000000011,
                "game_date": f"2027-04-0{offset}",
                "game_type": "R",
                "pitch_type": "FF",
                "description": description,
                "events": event,
                "stand": "R",
                "p_throws": "R",
                "delta_run_exp": value,
            }
            detail.append(row)
            if event:
                outcomes.append(
                    {
                        **row,
                        "game_year": 2027,
                        "is_pa": 1,
                        "fangraphs_woba_numer": 0.89,
                        "fangraphs_woba_denom": 1,
                    }
                )
    return {
        "schema": 1,
        "season": 2027,
        "synthetic": True,
        "date_from": "2027-04-01",
        "date_to": "2027-04-02",
        "game_type": "R",
        "rv_method": "context_neutral",
        "pitchers": [
            {
                "pitcher_id": pitcher,
                "season": 2027,
                "detail": detail,
                "rv_aggregate": [{"pitches": 6, "delev_pitcher_run_exp": -0.60}],
                "woba_detail": outcomes,
                "woba_aggregate": [{"pa": 2, "woba_value": 1.78, "woba": 0.89}],
            }
        ],
    }


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--staging-report", type=Path, required=True)
    parser.add_argument("--staging-sha", required=True)
    parser.add_argument("--bundle", type=Path)
    parser.add_argument("--bundle-sha")
    parser.add_argument("--synthetic", action="store_true")
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    try:
        report, staged = read_staged_sources(args.staging_report, args.staging_sha)
        require(args.synthetic is report["synthetic"], "Synthetic/real mode mismatch.")
        if args.synthetic:
            require(not args.bundle and not args.bundle_sha, "No synthetic overrides.")
            bundle = synthetic_bundle()
            bundle_evidence = None
        else:
            require(args.bundle and args.bundle_sha, "Reviewed official bundle required.")
            bundle_evidence = evidence(args.bundle)
            require(bundle_evidence["sha256"] == args.bundle_sha, "Bundle checksum mismatch.")
            bundle = read_json(args.bundle)
        if not args.synthetic:
            from scripts.acquire_future_savant import replay_bundle

            result = replay_bundle(report, staged, args.bundle, args.staging_sha, bundle)
        else:
            result = plan_all(report, staged, bundle)
        require(sha(args.staging_report) == args.staging_sha, "Staging report changed.")
        if not args.synthetic:
            require(evidence(args.bundle) == bundle_evidence, "Evidence changed during review.")
        result["staging_report_sha256"] = args.staging_sha
        result["bundle_evidence"] = bundle_evidence
        save(args.output, result)
        print(result["status"])
        print(
            f"Pitchers: {result['pitchers']}; pitches: {result['pitches']}; "
            f"PA: {result['official_pa']}; revisions: {len(result['revisions'])}; "
            f"planned patches: {len(result['patches'])}"
        )
        print("No database writes or publication performed.")
        return int(bool(result["revisions"]))
    except (OSError, ValueError, TypeError, KeyError, IndexError, ReleaseError) as exc:
        print("RECONCILIATION_FAILED:", str(exc))
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
