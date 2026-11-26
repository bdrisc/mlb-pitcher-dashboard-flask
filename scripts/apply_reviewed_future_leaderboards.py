"""Import independently reviewed real evidence into a new isolated candidate."""

from __future__ import annotations

import argparse
import json
import os
from pathlib import Path
from uuid import uuid4

from scripts import snapshot_integrity as integrity
from scripts.acquire_future_crosswalk import planned_mapping
from scripts.apply_future_corrections import clone_staging, snapshot
from scripts.apply_future_leaderboards import COLUMNS, apply_transaction
from scripts.rehearse_snapshot_release import (
    clean_checkout,
    commit,
    connect,
    recovery_url,
    require,
    save,
    sha,
)
from scripts.validate_future_release_evidence import input_paths, review, run

DECISION = "APPROVE_QUARANTINED_REAL_LEADERBOARD_IMPORT"


def expected_approval(season, inputs_sha, package_sha, package):
    require(
        package["synthetic"] is False
        and package["status"] == "PACKAGE_A_EVIDENCE_REVIEW_REQUIRED"
        and package["production_write_allowed"] is False
        and package["season"] == season
        and type(season) is int
        and season >= 2027,
        "Not real reviewed evidence.",
    )
    return {
        "schema": 1,
        "decision": DECISION,
        "synthetic": False,
        "season": season,
        "inputs_sha256": inputs_sha,
        "package_a_sha256": package_sha,
        "coverage": package["leaderboard_coverage"],
        "reviewed_game_results": package["game_results"],
        "crosswalk_report_sha256": package["crosswalk_report_sha256"],
        "full_regular_season_to_date_reviewed": True,
        "source_compatibility_reviewed": True,
        "nonpitch_events_reviewed": True,
        "missing_values_accepted_as_unavailable": True,
        "production_write_allowed": False,
    }


def validate_approval(approval, season, inputs_sha, package_sha, package):
    expected = expected_approval(season, inputs_sha, package_sha, package)
    notes = approval.get("review_notes")
    require(
        isinstance(notes, str)
        and bool(notes.strip())
        and approval == {**expected, "review_notes": notes},
        "Missing exact real-season coverage, identity and operator approval.",
    )


def load_approved(args):
    require(
        sha(args.inputs) == args.inputs_sha
        and sha(args.package_a) == args.package_a_sha
        and sha(args.approval) == args.approval_sha,
        "Approved input checksum mismatch.",
    )
    inputs = json.loads(args.inputs.read_bytes())
    package = run(
        inputs, False, args.register_commit, verify_report=args.package_a,
        report_sha=args.package_a_sha,
    )
    stage, staged, leaderboard, scope, _ = review(inputs, False)
    approval = json.loads(args.approval.read_bytes())
    validate_approval(approval, stage["season"], args.inputs_sha, args.package_a_sha, package)
    mapping = planned_mapping(leaderboard, scope["people"])
    cross = args.package_a.parent / "crosswalk" / "crosswalk_evidence.json"
    require(sha(cross) == package["crosswalk_report_sha256"], "Crosswalk checksum mismatch.")
    identities = json.loads(cross.read_bytes())["identities"]
    require(
        {int(pid): row["fangraphs_id"] for pid, row in identities.items()} == mapping,
        "Independent identities differ from approved leaderboard rows.",
    )
    paths = input_paths(inputs, False)
    correction = json.loads(paths["correction"].read_bytes())
    return inputs, stage, staged, leaderboard, correction, mapping


def apply(args):
    from dotenv import load_dotenv

    from app.config import database_url

    load_dotenv(integrity.ROOT / ".env")
    clean_checkout()
    code = commit()
    references = integrity.reference_hashes()
    for key in list(os.environ):
        if key.upper().startswith("PG"):
            del os.environ[key]
    approved = load_approved(args)
    _, stage, staged, leaderboard, correction, mapping = approved
    season = stage["season"]
    source = recovery_url(database_url(), correction["candidate_database"])
    target = recovery_url(database_url(), "mlb_release_candidate_" + uuid4().hex[:12])
    before = correction["candidate_fingerprint"]
    require(snapshot(source, season) == before, "Corrected candidate changed.")
    args.output.mkdir(parents=True, exist_ok=False)
    clone_staging(source, target)
    with connect(target) as conn:
        after, identities = apply_transaction(
            conn, target.database, staged, leaderboard, before, mapping
        )
    require(
        snapshot(target, season) == after and snapshot(source, season) == before,
        "Candidate or source changed.",
    )
    require(load_approved(args) == approved, "Approved real evidence changed.")
    require(integrity.reference_hashes() == references and commit() == code, "Code changed.")
    clean_checkout()
    result = {
        "schema": 1,
        "status": "REAL_LEADERBOARD_IMPORT_PASS_QUARANTINED",
        "synthetic": False,
        "season": season,
        "commit": code,
        "package_a_sha256": args.package_a_sha,
        "approval_sha256": args.approval_sha,
        "inputs_sha256": args.inputs_sha,
        "source_database": source.database,
        "candidate_database": target.database,
        "source_fingerprint": before,
        "candidate_fingerprint": after,
        "historical_fingerprint": correction["historical_fingerprint"],
        "identity_mapping": identities,
        "inserted_rows": {table: len(leaderboard[table]) for table in COLUMNS},
        "production_write_allowed": False,
    }
    save(args.output / "real_leaderboard_import_report.json", result)
    print(result["status"])
    print("Candidate remains quarantined; no publication performed.")


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    for name in ("inputs", "package-a", "approval", "output"):
        parser.add_argument("--" + name, type=Path, required=True)
    for name in ("inputs-sha", "package-a-sha", "approval-sha", "register-commit"):
        parser.add_argument("--" + name, required=True)
    args = parser.parse_args()
    try:
        apply(args)
        return 0
    except Exception as exc:
        print("REAL_IMPORT_FAILED:", str(exc) if isinstance(exc, ValueError) else type(exc).__name__)
        print("No publication attempted. Isolated artifacts retained.")
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
