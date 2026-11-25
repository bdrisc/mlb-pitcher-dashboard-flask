"""Apply an approved reconciliation plan only to a fresh isolated database clone."""

from __future__ import annotations

import argparse
import hashlib
import os
from collections import defaultdict
from math import fsum
from pathlib import Path
from uuid import uuid4

from scripts import snapshot_integrity as integrity
from scripts.reconcile_future_sources import (
    plan_all,
    read_json,
    read_staged_sources,
    synthetic_bundle,
)
from scripts.rehearse_snapshot_release import (
    ReleaseError,
    assert_identity,
    clean_checkout,
    commit,
    connect,
    evidence,
    recovery_url,
    require,
    reviewed_inputs,
    save,
    sha,
)
from scripts.stage_future_ingestion import (
    historical_fingerprint,
    original_players,
    verify_new_rows,
)

FIELDS = ("delta_run_expectancy", "savant_woba_numerator", "savant_woba_denominator")
PASS = "RECONCILIATION_PLAN_PASS_NOT_APPLIED"


def approved_plan(args):
    report, staged = read_staged_sources(args.staging_report, args.staging_sha)
    require(sha(args.plan) == args.plan_sha, "Plan checksum mismatch.")
    plan = read_json(args.plan)
    require(
        plan["status"] == PASS
        and plan["production_write_allowed"] is False
        and plan["synthetic"] is report["synthetic"] is args.synthetic,
        "Plan has not passed or has the wrong provenance.",
    )
    if args.synthetic:
        require(args.bundle is None, "No synthetic evidence override.")
        bundle = synthetic_bundle()
        bundle_evidence = None
    else:
        require(args.bundle is not None, "The reviewed evidence bundle is required.")
        bundle_evidence = evidence(args.bundle)
        require(bundle_evidence == plan["bundle_evidence"], "Evidence bundle changed.")
        bundle = read_json(args.bundle)
    rebuilt = plan_all(report, staged, bundle)
    rebuilt["staging_report_sha256"] = args.staging_sha
    rebuilt["bundle_evidence"] = bundle_evidence
    require(rebuilt == plan, "Plan cannot be reproduced from reviewed evidence.")
    require(
        sha(args.staging_report) == args.staging_sha and sha(args.plan) == args.plan_sha,
        "Input changed during verification.",
    )
    if args.bundle is not None:
        require(evidence(args.bundle) == bundle_evidence, "Evidence changed during review.")
    return report, staged, plan


def clone_staging(source, target):
    from psycopg import sql

    require(
        source.database.startswith("mlb_release_candidate_")
        and target.database.startswith("mlb_release_candidate_")
        and source.database != target.database
        and source.set(database=target.database) == target,
        "Only distinct isolated databases on the same server may be cloned.",
    )
    with connect(source.set(database="postgres"), autocommit=True) as conn:
        assert_identity(conn, "postgres")
        with conn.cursor() as cur:
            cur.execute(
                sql.SQL("CREATE DATABASE {} TEMPLATE {}").format(
                    sql.Identifier(target.database), sql.Identifier(source.database)
                )
            )


def fingerprint(conn, season, *, ignore_corrections=False):
    """Hash all seven sealed tables, excluding only approved future fields if requested."""
    with conn.cursor() as cur:
        cur.execute("SET LOCAL TIME ZONE 'UTC'")
        cur.execute("SET LOCAL extra_float_digits = 3")
    tables = {}
    for table, order in integrity.TABLES.items():
        row = "to_jsonb(t)"
        params = ()
        if table == "pitches" and ignore_corrections:
            row = """
                CASE WHEN t.game_pk IN (SELECT game_pk FROM games WHERE season = %s)
                THEN to_jsonb(t) - ARRAY[
                    'delta_run_expectancy', 'savant_woba_numerator', 'savant_woba_denominator'
                ]::text[] ELSE to_jsonb(t) END
            """
            params = (season,)
        digest = hashlib.sha256()
        count = 0
        with conn.cursor(name="correction_fingerprint") as cur:
            cur.itersize = 4000
            cur.execute(
                f"SELECT encode(sha256(convert_to(({row})::text, 'UTF8')), 'hex') "
                f"FROM {table} t ORDER BY {order}",
                params,
            )
            for (value,) in cur:
                digest.update(value.encode("ascii"))
                count += 1
        tables[table] = {"rows": count, "sha256": digest.hexdigest()}
    return tables


def snapshot(url, season, *, ignore_corrections=False):
    with connect(url) as conn:
        with conn.cursor() as cur:
            cur.execute("SET TRANSACTION ISOLATION LEVEL REPEATABLE READ READ ONLY")
        assert_identity(conn, url.database)
        return fingerprint(conn, season, ignore_corrections=ignore_corrections)


def expected_patches(staged, plan):
    owners = {key: pitcher for pitcher, records in staged.items() for key in records}
    patches = {}
    for row in plan["patches"]:
        key = row["pitch_id"]
        require(
            set(row) == {"pitch_id", *FIELDS} and key in owners and key not in patches,
            "Unexpected or duplicated patch.",
        )
        patches[key] = (owners[key], *(row[field] for field in FIELDS))
    require(
        set(patches) == set(owners) and len(patches) == plan["pitches"],
        "Patch coverage differs from staged pitch coverage.",
    )
    return patches


def read_values(cur, season):
    cur.execute(
        """
        SELECT p.pitch_id, p.pitcher_id, p.delta_run_expectancy,
               p.savant_woba_numerator, p.savant_woba_denominator
        FROM pitches p JOIN games g USING(game_pk)
        WHERE g.season = %s ORDER BY p.pitch_id
        """,
        (season,),
    )
    return {row[0]: tuple(row[1:]) for row in cur}


def validate_totals(actual, plan):
    grouped = defaultdict(list)
    for owner, rv, numerator, denom in actual.values():
        grouped[owner].append((rv, numerator, denom))
    require(
        set(grouped) == {row["pitcher_id"] for row in plan["pitcher_results"]},
        "Pitcher coverage changed.",
    )
    for official in plan["pitcher_results"]:
        values = grouped[official["pitcher_id"]]
        pa = [(n, d) for _, n, d in values if n is not None or d is not None]
        require(
            all(n is not None and d in (0, 1) for n, d in pa),
            "Incomplete wOBA components.",
        )
        rv_total = -fsum(rv for rv, _, _ in values if rv is not None)
        require(
            len(values) == official["pitches"]
            and len(pa) == official["official_pa"]
            and abs(rv_total - official["rv_total_pitcher"]) <= 0.005
            and abs(fsum(n for n, _ in pa) - official["woba_numerator"]) <= 1e-7
            and sum(d for _, d in pa) == official["woba_denominator"],
            "Post-correction official aggregate mismatch.",
        )


def apply_transaction(conn, database, season, patches, plan, before, unchanged):
    """All updates and checks share one caller-owned PostgreSQL transaction."""
    with conn.cursor() as cur:
        cur.execute("SET TRANSACTION ISOLATION LEVEL REPEATABLE READ")
    assert_identity(conn, database)
    with conn.cursor() as cur:
        # Prevent competing changes during the verification and update transaction.
        cur.execute(
            "LOCK TABLE players, games, pitches, fangraphs_stuff, "
            "published_pitching_metrics, savant_active_spin, alembic_version "
            "IN SHARE ROW EXCLUSIVE MODE"
        )
    require(fingerprint(conn, season) == before, "Clone differs from verified staging.")
    with conn.cursor() as cur:
        prior = read_values(cur, season)
        require(
            set(prior) == set(patches)
            and all(prior[key][0] == row[0] for key, row in patches.items())
            and all(row[2:] == (None, None) for row in prior.values()),
            "Candidate is not the unreconciled staged snapshot.",
        )
        cur.executemany(
            """
            UPDATE pitches AS p SET delta_run_expectancy = %s,
                savant_woba_numerator = %s, savant_woba_denominator = %s
            FROM games AS g
            WHERE p.game_pk = g.game_pk AND g.season = %s
                AND g.game_type = 'R' AND p.pitch_id = %s AND p.pitcher_id = %s
            """,
            [
                (rv, numerator, denom, season, key, owner)
                for key, (owner, rv, numerator, denom) in patches.items()
            ],
        )
        require(cur.rowcount == len(patches), "Unexpected update count.")
        actual = read_values(cur, season)
        require(actual == patches, "Stored corrected values differ from plan.")
        validate_totals(actual, plan)
    require(
        fingerprint(conn, season, ignore_corrections=True) == unchanged,
        "A row or field outside the correction scope changed.",
    )
    return fingerprint(conn, season)


def run(args):
    from dotenv import load_dotenv

    load_dotenv(integrity.ROOT / ".env")
    from app.config import database_url

    clean_checkout()
    code = commit()
    report, staged, plan = approved_plan(args)
    baseline, _, _, recovery_name = reviewed_inputs(
        args.baseline, args.audit, args.backups, args.local_recovery, args.public_recovery
    )
    expected = baseline["snapshot"]["local"]
    require(report["historical_fingerprint"] == expected, "Staging baseline differs.")
    for key in list(os.environ):
        if key.upper().startswith("PG"):
            del os.environ[key]
    recovery = recovery_url(database_url(), recovery_name)
    source = recovery_url(database_url(), report["candidate_database"])
    target = recovery_url(database_url(), "mlb_release_candidate_" + uuid4().hex[:12])
    require(source.database.startswith("mlb_release_candidate_"), "Not a staging source.")
    recovery_dsn = recovery.render_as_string(hide_password=False)
    require(integrity.fingerprint(recovery_dsn, "local") == expected, "Recovery source changed.")
    season = report["season"]
    manifest = report["source_manifest"]
    paths = [args.staging_report.parent / "sources" / row["file"] for row in manifest["sources"]]
    schedule = {
        row["game_pk"]: row["game_date"] for records in staged.values() for row in records.values()
    }
    players = original_players(recovery, schedule)
    require(
        historical_fingerprint(source, players) == expected["tables"],
        "Original staged historical fingerprint changed.",
    )
    require(
        verify_new_rows(source, paths, season, manifest, schedule) == report["coverage"],
        "Original staged future values changed.",
    )
    patches = expected_patches(staged, plan)
    before = snapshot(source, season)
    unchanged = snapshot(source, season, ignore_corrections=True)
    args.output.mkdir(parents=True, exist_ok=False)
    clone_staging(source, target)
    print(f"Created isolated correction candidate: {target.database}", flush=True)
    with connect(target) as conn:
        after = apply_transaction(conn, target.database, season, patches, plan, before, unchanged)
        # psycopg commits on successful exit, and rolls back on any exception.
    require(snapshot(target, season) == after, "Committed correction fingerprint differs.")
    require(snapshot(source, season) == before, "Original staging database changed.")
    require(
        historical_fingerprint(target, players) == expected["tables"],
        "Corrected candidate historical rows changed.",
    )
    require(integrity.fingerprint(recovery_dsn, "local") == expected, "Recovery source changed.")
    require(
        integrity.reference_hashes() == baseline["snapshot"]["references"],
        "Historical references changed.",
    )
    require(commit() == code, "Code changed during correction.")
    clean_checkout()
    require(
        all(
            evidence(path) == {k: record[k] for k in ("bytes", "sha256")}
            for path, record in zip(paths, manifest["sources"], strict=True)
        )
        and sha(args.staging_report) == args.staging_sha
        and sha(args.plan) == args.plan_sha,
        "Reviewed inputs changed during correction.",
    )
    if args.bundle is not None:
        require(evidence(args.bundle) == plan["bundle_evidence"], "Evidence bundle changed.")
    result = {
        "schema": 1,
        "status": "CORRECTIONS_PASS_QUARANTINED",
        "season": season,
        "synthetic": args.synthetic,
        "commit": code,
        "source_database": source.database,
        "candidate_database": target.database,
        "plan_sha256": args.plan_sha,
        "staging_report_sha256": args.staging_sha,
        "patched_pitches": len(patches),
        "official_pa": plan["official_pa"],
        "pitcher_results": plan["pitcher_results"],
        "historical_fingerprint": expected,
        "source_fingerprint": before,
        "candidate_fingerprint": after,
        "unchanged_fields_fingerprint": unchanged,
        "production_write_allowed": False,
        "release_blockers": report["release_blockers"],
    }
    save(args.output / "correction_report.json", result)
    print(f"Corrected pitches: {len(patches):,}; official PA: {plan['official_pa']:,}")
    print("CORRECTIONS_PASS_QUARANTINED")
    print("Production publication remains blocked.")


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    for name in (
        "baseline",
        "audit",
        "backups",
        "local-recovery",
        "public-recovery",
        "staging-report",
        "plan",
        "output",
    ):
        parser.add_argument("--" + name, type=Path, required=True)
    parser.add_argument("--staging-sha", required=True)
    parser.add_argument("--plan-sha", required=True)
    parser.add_argument("--bundle", type=Path)
    parser.add_argument("--synthetic", action="store_true")
    args = parser.parse_args()
    try:
        run(args)
    except Exception as exc:
        message = (
            str(exc)
            if isinstance(exc, (ReleaseError, integrity.SnapshotError))
            else type(exc).__name__
        )
        print("CORRECTIONS_FAILED:", message)
        print("No publication attempted. Any isolated candidate remains quarantined.")
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
