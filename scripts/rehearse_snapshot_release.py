"""Rehearse a release from the recovered 2026 snapshot, entirely on loopback PostgreSQL.

No live publication or remote database connection is implemented here.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import math
import os
import re
import shutil
import subprocess
from pathlib import Path
from urllib.parse import urlencode
from uuid import uuid4

from scripts import snapshot_integrity as integrity

ARCHIVES = {
    "local_verified.dump": (
        268304253,
        "2f1d0b64e2af0f87b46ef3e4ec5b983f5b04c608615e8608ecea4711fc31d0dd",
    ),
    "public_verified.dump": (
        31156502,
        "371b03e82afb73eeb031f0e4afde38aacfc32a9f603e5b16a85769c5facc2239",
    ),
}
PROFILE_KEYS = {
    "pitcher",
    "query",
    "sample",
    "overall",
    "arsenal",
    "pitch_roles",
    "platoon_splits",
    "pitch_separation",
    "pitch_tunneling",
    "fangraphs",
    "pitch_transition_matrix",
    "pitch_pair_effectiveness",
    "times_through_order_splits",
}
CHART_KEYS = {
    "movement",
    "velocity_trend",
    "inning_progression",
    "release_point",
    "location_heatmaps",
    "location_performance",
    "usage_by_count",
}
SKIP = {"reference_fangraphs_updated", "reference_savant_updated", "updated_at"}


class ReleaseError(ValueError):
    """A safe, actionable release preflight or audit failure."""


def require(condition, message):
    if not condition:
        raise ReleaseError(message)


def sha(path):
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def evidence(path):
    return {"bytes": path.stat().st_size, "sha256": sha(path)}


def save(path, payload):
    with path.open("x", encoding="utf-8") as handle:
        json.dump(payload, handle, indent=2, allow_nan=False)


def commit():
    return subprocess.check_output(
        ["git", "rev-parse", "HEAD"], cwd=integrity.ROOT, text=True
    ).strip()


def clean_checkout():
    changed = subprocess.check_output(
        ["git", "status", "--porcelain", "--untracked-files=no"],
        cwd=integrity.ROOT,
        text=True,
    )
    require(not changed.strip(), "Tracked code must be clean for a release rehearsal.")


def compare(a, b, path=""):
    if isinstance(a, dict) and isinstance(b, dict):
        for key in sorted(a.keys() | b.keys()):
            if key in SKIP or key.endswith("_updated_at"):
                continue
            child = f"{path}.{key}" if path else key
            if key not in a or key not in b:
                yield child
            else:
                yield from compare(a[key], b[key], child)
    elif isinstance(a, list) and isinstance(b, list):
        if len(a) != len(b):
            yield path + ".length"
        for index, (left, right) in enumerate(zip(a, b)):
            yield from compare(left, right, f"{path}[{index}]")
    else:
        numeric = (
            isinstance(a, (int, float))
            and not isinstance(a, bool)
            and isinstance(b, (int, float))
            and not isinstance(b, bool)
        )
        equal = (
            math.isfinite(a) and math.isfinite(b) and math.isclose(a, b, rel_tol=0, abs_tol=1e-7)
            if numeric
            else type(a) is type(b) and a == b
        )
        if not equal:
            yield path


def reviewed_inputs(baseline_path, audit_path, backup_dir, local_recovery, public_recovery):
    integrity.validate_report(audit_path)
    baseline = json.loads(baseline_path.read_bytes())
    require(
        baseline["audit_sha256"] == integrity.REPORT_SHA
        and baseline["snapshot"]["schema"] == 1
        and baseline["snapshot"]["references"] == integrity.reference_hashes(),
        "Reviewed baseline or league reference mismatch.",
    )
    for name, (size, digest) in ARCHIVES.items():
        require(
            evidence(backup_dir / name) == {"bytes": size, "sha256": digest},
            f"Archive mismatch: {name}",
        )
    local = json.loads(local_recovery.read_bytes())
    public = json.loads(public_recovery.read_bytes())
    baseline_hash = sha(baseline_path)
    require(
        local["baseline_sha256"] == public["baseline_sha256"] == baseline_hash,
        "Recovery reports do not match the baseline.",
    )
    local_record = local["results"]["local"]
    p = public["public"]
    for name, record in (("local", local_record), ("public", p)):
        require(
            all(
                record[key] == baseline["snapshot"][name][key]
                for key in ("tables", "coverage_2026")
            ),
            f"{name} restored fingerprint does not match.",
        )
    require(
        local_record["status"] == "PASS"
        and public["status"] == "BACKUP_RECOVERY_PASS"
        and public["archive_sha256"] == ARCHIVES["public_verified.dump"][1],
        "Both recovery tests must have passed.",
    )
    audit = json.loads(audit_path.read_bytes())
    rows = audit["results"]
    keys = {(r["pitcher_id"], r["endpoint"], r["scope"]) for r in rows}
    cohort = sorted(
        r["pitcher_id"] for r in rows if r["scope"] == "full" and r["endpoint"] == "profile"
    )
    require(
        len(keys) == len(rows) == 660 and len(set(cohort)) == len(cohort) == 50,
        "Unexpected reviewed comparison plan.",
    )
    require(
        sum(r["local_pitches"] for r in rows if r["scope"] == "full" and r["endpoint"] == "profile")
        == 142141,
        "Unexpected reviewed cohort coverage.",
    )
    return baseline, audit, cohort, local_record["database"]


def recovery_url(original, database):
    from sqlalchemy.engine import make_url

    parsed = make_url(original)
    require(
        parsed.get_backend_name() == "postgresql"
        and parsed.host in {"localhost", "127.0.0.1", "::1"}
        and parsed.database
        and parsed.username
        and not parsed.query,
        "Only an explicit loopback PostgreSQL URL without overrides is supported.",
    )
    require(
        re.fullmatch(r"mlb_(?:recovery_local|release_candidate)_[0-9a-f]{12}", database)
        and database != parsed.database,
        "Refusing a non-isolated database name.",
    )
    return parsed.set(database=database)


def connect(url, **options):
    import psycopg

    return psycopg.connect(
        url.set(drivername="postgresql").render_as_string(hide_password=False),
        connect_timeout=10,
        **options,
    )


def assert_identity(conn, expected):
    with conn.cursor() as cur:
        cur.execute("SELECT host(inet_server_addr()), current_database()")
        host, name = cur.fetchone()
    require(
        host in {"127.0.0.1", "::1"} and name == expected,
        "Database identity or loopback check failed.",
    )


def clone_candidate(source, target):
    from psycopg import sql

    require(source.database.startswith("mlb_recovery_local_"), "Invalid source.")
    require(target.database.startswith("mlb_release_candidate_"), "Invalid candidate.")
    require(source.database != target.database, "Source and candidate must differ.")
    with connect(source.set(database="postgres"), autocommit=True) as conn:
        assert_identity(conn, "postgres")
        with conn.cursor() as cur:
            cur.execute(
                sql.SQL("CREATE DATABASE {} TEMPLATE {}").format(
                    sql.Identifier(target.database), sql.Identifier(source.database)
                )
            )


def derive_cohort(target, cohort):
    require(target.database.startswith("mlb_release_candidate_"), "Not a candidate.")
    with connect(target) as conn:
        assert_identity(conn, target.database)
        with conn.cursor() as cur:
            cur.execute(
                """
                DELETE FROM pitches p USING games g
                WHERE p.game_pk = g.game_pk
                AND (g.season <> 2026 OR g.game_type IS DISTINCT FROM 'R'
                     OR NOT (p.pitcher_id = ANY(%s)))
                """,
                (cohort,),
            )
            cur.execute(
                "DELETE FROM games g WHERE NOT EXISTS "
                "(SELECT 1 FROM pitches p WHERE p.game_pk = g.game_pk)"
            )
            cur.execute(
                """
                DELETE FROM players WHERE mlb_id NOT IN (
                    SELECT pitcher_id FROM pitches UNION SELECT batter_id FROM pitches
                )
                """
            )
            # Public published tables intentionally contain the full league for 2026.
            for table in ("fangraphs_stuff", "published_pitching_metrics", "savant_active_spin"):
                cur.execute(f"DELETE FROM {table} WHERE season <> 2026")
            # Do not publish local ingestion history or private source paths.
            cur.execute("DELETE FROM ingestion_runs")
            cur.execute("SELECT DISTINCT pitcher_id FROM pitches ORDER BY pitcher_id")
            require([r[0] for r in cur] == cohort, "Candidate cohort mismatch.")
            cur.execute("SELECT count(*) FROM pitches")
            require(cur.fetchone()[0] == 142141, "Candidate pitch count mismatch.")


def app_for(url):
    from app import create_app

    # Explicit factory config overrides DATABASE_URL loaded from .env.
    return create_app(
        {
            "TESTING": True,
            "APP_ENV": "test",
            "SQLALCHEMY_DATABASE_URI": url.render_as_string(hide_password=False),
            "SQLALCHEMY_ENGINE_OPTIONS": {
                "connect_args": {"options": "-c default_transaction_read_only=on"},
            },
        }
    )


def fetch(app, path):
    response = app.test_client().get(path)
    return response.status_code, response.get_json()


def audit_candidates(source, target, audit, cohort):
    left, right = app_for(source), app_for(target)
    ls, a = fetch(left, "/api/v1/pitchers?season=2026")
    rs, b = fetch(right, "/api/v1/pitchers?season=2026")
    require(ls == rs == 200, "Candidate index request failed.")
    local_index = {row["mlb_id"]: row for row in a["pitchers"]}
    r = {row["mlb_id"]: row for row in b["pitchers"]}
    require(
        len(local_index) == 868
        and len(r) == len(b["pitchers"]) == 50
        and sorted(r) == cohort
        and sum(x["pitch_count"] for x in r.values()) == 142141,
        "Candidate index coverage mismatch.",
    )
    index_diff = list(compare({str(k): local_index[k] for k in r}, {str(k): r[k] for k in r}))
    results = []
    for plan in audit["results"]:
        pid, endpoint, scope = (plan[k] for k in ("pitcher_id", "endpoint", "scope"))
        path = f"/api/v1/pitchers/{pid}/{endpoint}?" + urlencode(
            {"season": 2026, **plan["filters"]}, doseq=True
        )
        ls, a = fetch(left, path)
        rs, b = fetch(right, path)
        diff = list(compare(a, b))
        expected_status = plan["local_status"]
        valid = ls == rs == expected_status and isinstance(a, dict) and isinstance(b, dict)
        if expected_status == 200:
            for payload in (a, b):
                valid = valid and (
                    payload.get("sample", {}).get("pitches") == plan["local_pitches"]
                    and (
                        PROFILE_KEYS <= payload.keys()
                        if endpoint == "profile"
                        else CHART_KEYS <= payload.get("charts", {}).keys()
                    )
                )
                if endpoint == "profile" and scope == "full":
                    valid = valid and (
                        payload["pitch_roles"]["reference_sha256"] == integrity.ROLE_2026_SHA
                    )
        elif expected_status == 404:
            valid = (
                valid
                and scope == "empty_date"
                and all(
                    p.get("error") == "not_found" and p.get("pitcher_id") == pid for p in (a, b)
                )
            )
        else:
            valid = False
        result = {
            "pitcher_id": pid,
            "endpoint": endpoint,
            "scope": scope,
            "status": "PASS" if valid and not diff else "FAIL",
            "http": [ls, rs],
            "different_fields": len(diff),
            "examples": diff[:100],
        }
        results.append(result)
        print(f"{pid} {endpoint} {scope}: {result['status']}", flush=True)
    return {
        "index_differences": index_diff,
        "results": results,
        "status": "PASS"
        if not index_diff
        and len(results) == 660
        and all(row["status"] == "PASS" for row in results)
        else "FAIL",
    }


def export_candidate(target, output):
    from psycopg.conninfo import make_conninfo

    require(target.database.startswith("mlb_release_candidate_"), "Not a candidate.")
    exe = shutil.which("pg_dump")
    restore = shutil.which("pg_restore")
    require(exe and restore, "PostgreSQL backup utilities must be on PATH.")
    env = os.environ.copy()
    if target.password:
        env["PGPASSWORD"] = target.password
    dsn = make_conninfo(
        host=target.host,
        port=target.port or 5432,
        dbname=target.database,
        user=target.username,
        connect_timeout=10,
    )
    subprocess.run(
        [
            exe,
            "--format=custom",
            "--no-password",
            "--no-owner",
            "--no-privileges",
            "--file",
            str(output),
            "--dbname",
            dsn,
        ],
        env=env,
        check=True,
    )
    subprocess.run([restore, "--list", str(output)], stdout=subprocess.DEVNULL, check=True)


def rehearse(args):
    from dotenv import load_dotenv

    load_dotenv(integrity.ROOT / ".env")
    from app.config import database_url

    clean_checkout()
    code = commit()
    baseline, audit, cohort, source_name = reviewed_inputs(
        args.baseline, args.audit, args.backups, args.local_recovery, args.public_recovery
    )
    original = database_url()
    for key in list(os.environ):
        if key.upper().startswith("PG"):
            del os.environ[key]
    source = recovery_url(original, source_name)
    target = recovery_url(original, "mlb_release_candidate_" + uuid4().hex[:12])
    expected = baseline["snapshot"]["local"]
    require(
        integrity.fingerprint(source.render_as_string(hide_password=False), "local") == expected,
        "Recovered full-league source has drifted.",
    )
    args.output.mkdir(parents=True, exist_ok=False)
    print("SOURCE_FINGERPRINT_PASS", flush=True)
    clone_candidate(source, target)
    print(f"Created isolated candidate: {target.database}", flush=True)
    require(
        integrity.fingerprint(target.render_as_string(hide_password=False), "local") == expected,
        "Clone does not match full-league source.",
    )
    derive_cohort(target, cohort)
    candidate_url = target.render_as_string(hide_password=False)
    candidate = integrity.fingerprint(candidate_url, "public")
    print("CANDIDATE_COVERAGE_PASS", flush=True)
    report = audit_candidates(source, target, audit, cohort)
    save(args.output / "candidate_parity.json", report)
    require(report["status"] == "PASS", "Candidate failed parity; no release archive created.")
    require(
        integrity.fingerprint(source.render_as_string(hide_password=False), "local") == expected,
        "Recovered source changed during rehearsal.",
    )
    require(
        integrity.fingerprint(candidate_url, "public") == candidate,
        "Candidate changed during validation.",
    )
    require(
        integrity.reference_hashes() == baseline["snapshot"]["references"],
        "Historical reference changed during rehearsal.",
    )
    require(commit() == code, "Code changed during rehearsal.")
    clean_checkout()
    archive = args.output / "candidate_public_2026.dump"
    export_candidate(target, archive)
    require(
        integrity.fingerprint(candidate_url, "public") == candidate,
        "Candidate changed during export.",
    )
    manifest = {
        "schema": 1,
        "status": "REHEARSAL_PASS_NOT_PUBLISHED",
        "season": 2026,
        "commit": code,
        "source_database": source.database,
        "candidate_database": target.database,
        "cohort": cohort,
        "source_fingerprint": expected,
        "candidate_fingerprint": candidate,
        "reference_hashes": baseline["snapshot"]["references"],
        "inputs": {
            "baseline": evidence(args.baseline),
            "audit": evidence(args.audit),
            "local_recovery": evidence(args.local_recovery),
            "public_recovery": evidence(args.public_recovery),
            "source_archives": {name: evidence(args.backups / name) for name in ARCHIVES},
        },
        "artifacts": {
            name: evidence(args.output / name)
            for name in ("candidate_parity.json", "candidate_public_2026.dump")
        },
        "production_write_allowed": False,
    }
    save(args.output / "release_manifest.json", manifest)
    print("REHEARSAL_PASS_NOT_PUBLISHED", flush=True)
    print("Manifest SHA-256:", sha(args.output / "release_manifest.json"), flush=True)


def review(args):
    path = args.output / "release_manifest.json"
    require(sha(path) == args.manifest_sha, "Manifest checksum mismatch.")
    data = json.loads(path.read_bytes())
    require(
        data["schema"] == 1
        and data["season"] == 2026
        and data["status"] == "REHEARSAL_PASS_NOT_PUBLISHED"
        and data["production_write_allowed"] is False,
        "Not a passing historical rehearsal.",
    )
    clean_checkout()
    require(data["commit"] == commit(), "Code differs from the reviewed candidate.")
    require(data["reference_hashes"] == integrity.reference_hashes(), "References changed.")
    require(
        set(data["artifacts"]) == {"candidate_parity.json", "candidate_public_2026.dump"},
        "Missing or unexpected release artifacts.",
    )
    for name, expected in data["artifacts"].items():
        require(evidence(args.output / name) == expected, f"Artifact changed: {name}")
    audit = json.loads((args.output / "candidate_parity.json").read_bytes())
    require(
        audit["status"] == "PASS"
        and not audit["index_differences"]
        and len(audit["results"]) == 660
        and len({(r["pitcher_id"], r["endpoint"], r["scope"]) for r in audit["results"]}) == 660
        and all(r["status"] == "PASS" and r["different_fields"] == 0 for r in audit["results"]),
        "Rehearsal parity evidence failed.",
    )
    print("REHEARSAL_REVIEW_PASS_NO_PUBLICATION")
    print("This gate never authorizes or performs production writes.")


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    sub = parser.add_subparsers(dest="mode", required=True)
    run = sub.add_parser("rehearse")
    for name in ("baseline", "audit", "backups", "local-recovery", "public-recovery", "output"):
        run.add_argument("--" + name, type=Path, required=True)
    gate = sub.add_parser("review")
    gate.add_argument("--output", type=Path, required=True)
    gate.add_argument("--manifest-sha", required=True)
    args = parser.parse_args()
    try:
        (rehearse if args.mode == "rehearse" else review)(args)
    except Exception as exc:
        print(
            "RELEASE_CHECK_FAILED:",
            str(exc) if isinstance(exc, ReleaseError) else type(exc).__name__,
        )
        print("No live publication was attempted. Isolated candidates are retained.")
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
