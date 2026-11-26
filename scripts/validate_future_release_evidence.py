"""Package A: unified read-only evidence validation and independent archive replay."""

from __future__ import annotations

import argparse
import json
from pathlib import Path
from types import SimpleNamespace

from scripts import acquire_future_crosswalk as crosswalk
from scripts import acquire_future_mlb_scope as mlb_scope
from scripts import future_game_feed as game_feed
from scripts.acquire_future_leaderboards import build_report, validate_correction
from scripts.acquire_future_savant import replay_bundle
from scripts.apply_future_corrections import approved_plan
from scripts.reconcile_future_sources import read_staged_sources
from scripts.rehearse_snapshot_release import require, save, sha

SYNTHETIC_FILES = {
    "staging": "future_staging_synthetic_01/staging_report.json",
    "plan": "future_staging_synthetic_01/reconciliation_plan.json",
    "correction": "future_corrections_synthetic_01/correction_report.json",
    "savant": "future_savant_evidence_synthetic_01/evidence_bundle.json",
    "leaderboard": "future_leaderboard_evidence_synthetic_01/leaderboard_evidence.json",
    "scope": "future_mlb_scope_synthetic_01/mlb_scope_evidence.json",
    "import": "future_leaderboard_import_synthetic_01/leaderboard_import_report.json",
}


def synthetic_inputs(backup):
    # Local fixture reports have already been rehearsed. Real inputs must use
    # externally reviewed hashes, never hashes freshly derived at acquisition.
    return {
        name: {"path": str(backup / path), "sha256": sha(backup / path)}
        for name, path in SYNTHETIC_FILES.items()
    }


def input_paths(inputs, synthetic):
    expected = set(SYNTHETIC_FILES)
    if not synthetic:
        expected.remove("import")
    require(set(inputs) == expected, "Missing or extra approved input reports.")
    paths = {}
    for name, record in inputs.items():
        path = Path(record["path"])
        require(sha(path) == record["sha256"], f"Input checksum mismatch: {name}")
        paths[name] = path
    return paths


def check_import(import_report, correction, leaderboard, hashes):
    require(
        import_report["schema"] == 1
        and import_report["status"] == "LEADERBOARD_IMPORT_PASS_QUARANTINED"
        and import_report["synthetic"] is True
        and import_report["production_write_allowed"] is False
        and import_report["season"] == correction["season"]
        and import_report["correction_report_sha256"] == hashes["correction"]
        and import_report["staging_report_sha256"] == hashes["staging"]
        and import_report["leaderboard_report_sha256"] == hashes["leaderboard"]
        and import_report["source_database"] == correction["candidate_database"]
        and import_report["source_fingerprint"] == correction["candidate_fingerprint"]
        and import_report["historical_fingerprint"] == correction["historical_fingerprint"],
        "Leaderboard import checkpoint differs from approved correction.",
    )
    counts = import_report["inserted_rows"]
    before = correction["candidate_fingerprint"]
    after = import_report["candidate_fingerprint"]
    require(
        set(before) == set(after)
        and all(before[t] == after[t] for t in before if t not in counts)
        and all(after[t]["rows"] == before[t]["rows"] + n for t, n in counts.items())
        and counts
        == {
            table: len(leaderboard[table])
            for table in ("fangraphs_stuff", "published_pitching_metrics", "savant_active_spin")
        },
        "Import checkpoint row counts or unaffected fingerprints differ.",
    )


def review(inputs, synthetic):
    paths = input_paths(inputs, synthetic)
    hashes = {name: record["sha256"] for name, record in inputs.items()}
    stage, staged = read_staged_sources(paths["staging"], hashes["staging"])
    require(stage["synthetic"] is synthetic, "Synthetic/real mode mismatch.")
    validate_correction(
        paths["correction"], hashes["correction"], stage, staged, hashes["staging"]
    )
    correction = json.loads(paths["correction"].read_bytes())
    require(correction["plan_sha256"] == hashes["plan"], "Correction plan binding differs.")
    args = SimpleNamespace(
        staging_report=paths["staging"],
        staging_sha=hashes["staging"],
        plan=paths["plan"],
        plan_sha=hashes["plan"],
        synthetic=synthetic,
        bundle=None if synthetic else paths["savant"],
    )
    _, _, plan = approved_plan(args)
    bundle = json.loads(paths["savant"].read_bytes())
    replayed = replay_bundle(stage, staged, paths["savant"], hashes["staging"], bundle)
    require(
        replayed
        == {
            k: v
            for k, v in plan.items()
            if k not in ("staging_report_sha256", "bundle_evidence")
        }
        and correction["official_pa"] == plan["official_pa"]
        and correction["pitcher_results"] == plan["pitcher_results"],
        "Archived Savant evidence differs from corrected plan.",
    )
    leaderboard = json.loads(paths["leaderboard"].read_bytes())
    require(
        leaderboard
        == build_report(
            stage,
            staged,
            paths["leaderboard"].parent / "raw",
            leaderboard["responses"],
            hashes["staging"],
            hashes["correction"],
        ),
        "Leaderboard evidence replay differs.",
    )
    scope = json.loads(paths["scope"].read_bytes())
    require(
        scope
        == mlb_scope.rebuild(
            stage,
            staged,
            paths["scope"].parent / "raw",
            scope["responses"],
            hashes["staging"],
            scope["window"]["start"],
            scope["window"]["end"],
        ),
        "MLB scope evidence replay differs.",
    )
    if synthetic:
        check_import(
            json.loads(paths["import"].read_bytes()), correction, leaderboard, hashes
        )
    return stage, staged, leaderboard, scope, hashes


def coverage(leaderboard):
    return {
        "sources": leaderboard["coverage"],
        "missing_values": leaderboard["missing_values"],
        "unmapped_grades": leaderboard["unmapped_fangraphs_grades"],
        "unmapped_rates": leaderboard["unmapped_fangraphs_rates"],
        "spin_season_in_response": leaderboard["spin_season_in_response"],
    }


def clean_coverage(reviewed):
    return (
        not reviewed["missing_values"]
        and not reviewed["unmapped_grades"]
        and not reviewed["unmapped_rates"]
        and reviewed["spin_season_in_response"]
        and all(
            not row["missing_staged_pitchers"] and not row["outside_staging_pitchers"]
            for row in reviewed["sources"].values()
        )
    )


def finish(reviewed, cross, feeds, records, cross_sha):
    stage, staged, leaderboard, _, hashes = reviewed
    cov = coverage(leaderboard)
    physical = sum(row["physical_pitches"] for row in feeds.values())
    require(
        physical == sum(map(len, staged.values())),
        "Physical pitch coverage does not match staged rows.",
    )
    if stage["synthetic"]:
        require(clean_coverage(cov), "Synthetic leaderboard coverage not complete.")
    return {
        "schema": 1,
        "status": (
            "PACKAGE_A_SYNTHETIC_PASS_NOT_APPLIED"
            if stage["synthetic"]
            else "PACKAGE_A_EVIDENCE_REVIEW_REQUIRED"
        ),
        "season": stage["season"],
        "synthetic": stage["synthetic"],
        "input_sha256": hashes,
        "crosswalk_report_sha256": cross_sha,
        "crosswalk_mappings": len(cross["identities"]),
        "completed_games": len(feeds),
        "physical_pitches": physical,
        "game_results": feeds,
        "game_responses": records,
        "leaderboard_coverage": cov,
        "real_coverage_review_required": True,
        "real_nonpitch_event_review_required": True,
        "real_source_compatibility_verified": False,
        "production_write_allowed": False,
    }


def run(inputs, synthetic, revision, output=None, verify_report=None, report_sha=None):
    reviewed = review(inputs, synthetic)
    stage, staged, leaderboard, scope, hashes = reviewed
    expected = crosswalk.planned_mapping(leaderboard, scope["people"])
    bindings = {k: hashes[k] for k in ("staging", "correction", "leaderboard", "scope")}
    if verify_report:
        require(sha(verify_report) == report_sha, "Package report checksum mismatch.")
        original = json.loads(verify_report.read_bytes())
        root = verify_report.parent
        records = original["game_responses"]
    else:
        output.mkdir(parents=True, exist_ok=False)
        root = output
        crosswalk.acquire(
            root / "crosswalk", revision, synthetic, expected, stage["season"], bindings
        )
        records = game_feed.acquire(
            root / "games", game_feed.group_games(staged), synthetic
        )
    cross_path = root / "crosswalk" / "crosswalk_evidence.json"
    cross = json.loads(cross_path.read_bytes())
    cross_sha = sha(cross_path)
    require(
        cross
        == crosswalk.build_evidence(
            cross_path.parent / "raw",
            cross["responses"],
            revision,
            synthetic,
            expected,
            stage["season"],
            bindings,
        ),
        "Independent crosswalk replay differs.",
    )
    feeds = game_feed.replay(
        root / "games", records, staged, scope["completed_games"], stage["season"], synthetic
    )
    result = finish(reviewed, cross, feeds, records, cross_sha)
    input_paths(inputs, synthetic)
    require(sha(cross_path) == cross_sha, "Crosswalk report changed during verification.")
    if verify_report:
        require(
            result == original and sha(verify_report) == report_sha,
            "Package report differs from replay.",
        )
    else:
        save(root / "package_a_report.json", result)
    return result


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--synthetic-backup", type=Path)
    parser.add_argument("--inputs", type=Path)
    parser.add_argument("--inputs-sha")
    parser.add_argument("--register-commit")
    parser.add_argument("--output", type=Path)
    parser.add_argument("--verify-report", type=Path)
    parser.add_argument("--report-sha")
    args = parser.parse_args()
    try:
        require(
            bool(args.synthetic_backup) != bool(args.inputs),
            "Choose synthetic backup or reviewed real input manifest.",
        )
        require(bool(args.output) != bool(args.verify_report), "Choose acquisition or replay.")
        synthetic = args.synthetic_backup is not None
        if synthetic:
            require(not args.register_commit and not args.inputs_sha, "No fixture overrides.")
            inputs = synthetic_inputs(args.synthetic_backup)
            revision = crosswalk.FIXTURE_COMMIT
        else:
            require(
                bool(args.register_commit) and sha(args.inputs) == args.inputs_sha,
                "Require pinned register commit and reviewed real manifest digest.",
            )
            inputs = json.loads(args.inputs.read_bytes())
            revision = args.register_commit
        result = run(
            inputs, synthetic, revision, args.output, args.verify_report, args.report_sha
        )
        if not synthetic:
            require(sha(args.inputs) == args.inputs_sha, "Input manifest changed.")
        print(f"Crosswalk mappings: {result['crosswalk_mappings']}")
        print(f"Completed games: {result['completed_games']}")
        print(f"Physical pitches: {result['physical_pitches']}")
        print(result["status"])
        print("No database writes or publication performed.")
        return 0
    except Exception as exc:
        print("PACKAGE_A_FAILED:", str(exc) if isinstance(exc, ValueError) else type(exc).__name__)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
