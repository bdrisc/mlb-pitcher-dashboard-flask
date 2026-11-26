"""Package C: replay evidence, derive a quarantined cohort, audit and restore it."""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import shutil
import subprocess
from datetime import date
from pathlib import Path
from unittest.mock import patch
from urllib.parse import urlencode
from uuid import uuid4

from scripts import snapshot_integrity as integrity
from scripts.apply_future_corrections import clone_staging, snapshot
from scripts.build_future_season_references import (
    coefficient_evidence,
    location_payload,
    physical_scope,
)
from scripts.rehearse_snapshot_release import (
    CHART_KEYS,
    PROFILE_KEYS,
    app_for,
    assert_identity,
    audit_candidates,
    clean_checkout,
    commit,
    compare,
    connect,
    evidence,
    export_candidate,
    fetch,
    recovery_url,
    require,
    reviewed_inputs,
    save,
    sha,
)
from scripts.stage_future_ingestion import historical_fingerprint, original_players
from scripts.validate_future_release_evidence import input_paths, run, synthetic_inputs

SEASON = 2027
FIXTURE_PITCHER = 2000000010
BLOCKERS = [
    "synthetic_data_never_publish",
    "real_provider_compatibility_and_scope_review",
    "real_leaderboard_import_and_reference_approval",
    "exact_live_public_history_preservation",
    "real_candidate_deployment_and_rollback_review",
    "explicit_operator_publication_approval",
]


def read(path):
    return json.loads(path.read_bytes())


def fingerprint_digest(value):
    raw = json.dumps(value, sort_keys=True, separators=(",", ":")).encode()
    return hashlib.sha256(raw).hexdigest()


def check_package_b(path, a_sha, correction, references):
    report = read(path)
    entry = report["entry"]
    require(
        report["schema"] == 1
        and report["status"] == "PACKAGE_B_SYNTHETIC_PASS_NOT_APPLIED"
        and report["production_write_allowed"] is False
        and report["registry_updated"] is False
        and report["historical_reference_hashes"] == references
        and report["candidate_fingerprint"] == correction["candidate_fingerprint"]
        and entry["candidate_fingerprint_sha256"]
        == fingerprint_digest(correction["candidate_fingerprint"])
        and entry["season"] == SEASON
        and entry["synthetic"] is True
        and entry["coverage"] == [1, 6, 6, 2]
        and entry["start"] == "2027-04-01"
        and entry["through"] == "2027-04-02"
        and entry["package_a_sha256"] == a_sha
        and set(entry["artifacts"]) == {"location"}
        and set(report["unavailable_references"]) == {"movement", "roles"},
        "Package B checkpoint does not match the approved fixture.",
    )
    item = entry["artifacts"]["location"]
    require(item["file"] == "league_location_2027.json.gz", "Unexpected location artifact.")
    from app.services.future_season_references import digest

    location = path.parent / item["file"]
    require(digest(location) == item["sha256"], "Location artifact checksum mismatch.")
    raw = (path.parent / "guts_source.csv").read_bytes()
    require(
        entry["coefficients"] == coefficient_evidence(raw, SEASON, entry["through"]),
        "Coefficient archive differs from Package B.",
    )
    return report


def derive_future_cohort(source, target, historical_ids, future_ids):
    """Delete only from a newly created, isolated clone, never a live database."""
    require(
        source.database.startswith("mlb_release_candidate_")
        and target.database.startswith("mlb_release_candidate_")
        and target != source
        and source.set(database=target.database) == target,
        "Refusing non-isolated cohort derivation.",
    )
    require(bool(historical_ids) and bool(future_ids), "Cohorts cannot be empty.")
    with connect(target) as conn:
        assert_identity(conn, target.database)
        with conn.cursor() as cur:
            cur.execute(
                """
                DELETE FROM pitches p USING games g WHERE p.game_pk = g.game_pk
                AND NOT (
                    (g.season = 2026 AND g.game_type = 'R' AND p.pitcher_id = ANY(%s))
                    OR (g.season = %s AND g.game_type = 'R' AND p.pitcher_id = ANY(%s))
                )
                """,
                (historical_ids, SEASON, future_ids),
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
            for table in ("fangraphs_stuff", "published_pitching_metrics", "savant_active_spin"):
                cur.execute(f"DELETE FROM {table} WHERE season NOT IN (2026, %s)", (SEASON,))
            cur.execute("DELETE FROM ingestion_runs")
            for year, ids, count in (
                (2026, historical_ids, 142141),
                (SEASON, future_ids, 6),
            ):
                cur.execute(
                    """
                    SELECT count(*), array_agg(DISTINCT p.pitcher_id ORDER BY p.pitcher_id)
                    FROM pitches p JOIN games g USING(game_pk) WHERE g.season = %s
                    """,
                    (year,),
                )
                require(cur.fetchone() == (count, ids), "Derived cohort coverage mismatch.")


def future_plan():
    return [
        ("full", {}, 6),
        ("right", {"batter_side": "R"}, 6),
        ("left_empty", {"batter_side": "L"}, 0),
        ("ff", {"pitch_type": "FF"}, 6),
        ("sl_empty", {"pitch_type": "SL"}, 0),
        ("home", {"home_away": "home"}, 6),
        ("away_empty", {"home_away": "away"}, 0),
        ("team", {"team": "BOS"}, 6),
        ("first_day", {"date_from": "2027-04-01", "date_to": "2027-04-01"}, 3),
        ("second_day", {"date_from": "2027-04-02", "date_to": "2027-04-02"}, 3),
        ("first_pitch", {"balls": 0, "strikes": 0}, 2),
        ("two_strikes", {"count_group": "two_strikes"}, 2),
        ("empty_date", {"date_from": "2027-04-03"}, 0),
    ]


def verify_future_profile(payload, full):
    overall = payload["overall"]
    require(
        overall["expected_run_value_per_100"] is None
        and overall["expected_run_value_quality"] == "unavailable"
        and not payload["pitch_roles"]["reference_available"]
        and all(p["hb_vs_avg"] is None and p["ivb_vs_avg"] is None for p in payload["arsenal"]),
        "Synthetic or unapproved future references escaped quarantine.",
    )
    if full:
        expected = {
            "run_value": -0.6,
            "run_value_per_100": -10.0,
            "woba_against": 0.89,
            "stuff_plus": 112,
            "location_plus": 104,
            "pitching_plus": 109,
            "fip": 3.2,
            "xfip": 3.5,
            "siera": 3.4,
            "xera": 3.1,
        }
        require(
            not list(compare(expected, {key: overall[key] for key in expected})),
            "Future profile does not match independently approved fixture totals.",
        )
        arsenal = payload["arsenal"]
        require(
            len(arsenal) == 1
            and arsenal[0]["pitch_type"] == "FF"
            and arsenal[0]["stuff_plus"] == 115
            and arsenal[0]["spin_efficiency_pct"] == 95.5,
            "Future pitch-level published metrics differ.",
        )


def dispose(app):
    from app.extensions import db

    with app.app_context():
        db.session.remove()
        db.engine.dispose()


class RehearsalDate(date):
    @classmethod
    def today(cls):
        return max(date.today(), date(SEASON, 4, 3))


def audit_future(source, target):
    # Only the isolated synthetic audit may advance the filter calendar.
    # The production API continues to reject future calendar years.
    with patch("app.services.filters.date", RehearsalDate):
        return _audit_future(source, target)


def _audit_future(source, target):
    left, right = app_for(source), app_for(target)
    try:
        path = "/api/v1/pitchers?season=2027"
        ls, a = fetch(left, path)
        rs, b = fetch(right, path)
        require(
            ls == rs == 200
            and not list(compare(a["pitchers"], b["pitchers"]))
            and a["query"] == b["query"]
            and len(a["pitchers"]) == 1
            and a["pitchers"][0]["mlb_id"] == FIXTURE_PITCHER
            and a["pitchers"][0]["pitch_count"] == 6,
            "Future pitcher index differs.",
        )
        results = []
        for name, filters, count in future_plan():
            for endpoint in ("profile", "charts"):
                query = urlencode({"season": SEASON, **filters})
                path = f"/api/v1/pitchers/{FIXTURE_PITCHER}/{endpoint}?{query}"
                ls, a = fetch(left, path)
                rs, b = fetch(right, path)
                require(
                    ls == rs == (200 if count else 404) and not list(compare(a, b)),
                    f"Future API mismatch: {name}/{endpoint}",
                )
                if count:
                    for payload in (a, b):
                        require(payload["sample"]["pitches"] == count, "Wrong pitch count.")
                        if endpoint == "profile":
                            require(PROFILE_KEYS <= payload.keys(), "Incomplete profile.")
                            verify_future_profile(payload, name == "full")
                        else:
                            charts = payload["charts"]
                            require(CHART_KEYS <= charts.keys(), "Incomplete charts.")
                            require(
                                charts["location_performance"]["league_bins"] == [],
                                "Unapproved location reference was exposed.",
                            )
                else:
                    require(
                        a["error"] == "not_found" and a["pitcher_id"] == FIXTURE_PITCHER,
                        "Unexpected empty filter response.",
                    )
                results.append({"scope": name, "endpoint": endpoint, "pitches": count, "http": ls})
        return {"status": "PASS", "results": results}
    finally:
        dispose(left)
        dispose(right)


def restore_archive(target, archive):
    from psycopg import sql
    from psycopg.conninfo import make_conninfo

    require(target.database.startswith("mlb_release_candidate_"), "Not a restore candidate.")
    exe = shutil.which("pg_restore")
    require(exe is not None, "pg_restore must be on PATH.")
    with connect(target.set(database="postgres"), autocommit=True) as conn:
        assert_identity(conn, "postgres")
        with conn.cursor() as cur:
            cur.execute(
                sql.SQL("CREATE DATABASE {} TEMPLATE template0").format(
                    sql.Identifier(target.database)
                )
            )
    with connect(target) as conn:
        assert_identity(conn, target.database)
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
            "--exit-on-error",
            "--single-transaction",
            "--no-owner",
            "--no-privileges",
            "--no-password",
            "--dbname",
            dsn,
            str(archive),
        ],
        env=env,
        check=True,
    )


def rehearse(backup, output):
    from dotenv import load_dotenv

    from app.config import database_url
    from app.services.future_season_references import REGISTRY, entries

    load_dotenv(integrity.ROOT / ".env")
    clean_checkout()
    code = commit()
    for key in list(os.environ):
        if key.upper().startswith("PG"):
            del os.environ[key]
    original = database_url()
    references = integrity.reference_hashes()
    registry_sha = sha(REGISTRY)
    require(read(REGISTRY) == {"schema": 1, "seasons": {}}, "Expected empty future registry.")
    require(not entries(), "A future-season reference is already active.")
    baseline, audit, cohort, recovery_name = reviewed_inputs(
        integrity.ROOT / "outputs/snapshot_integrity/verified_2026.json",
        integrity.ROOT / "extended_dashboard_parity_2026.json",
        backup,
        backup / "recovery_test_1e9698ec9b81.json",
        backup / "recovery_public_1712_35b9ea2c5f52.json",
    )
    inputs = synthetic_inputs(backup)
    paths = input_paths(inputs, True)
    a_path = backup / "package_a_synthetic_01" / "package_a_report.json"
    b_path = backup / "package_b_synthetic_01" / "package_b_report.json"
    a_sha, b_sha = sha(a_path), sha(b_path)
    approved = run(inputs, True, "synthetic", verify_report=a_path, report_sha=a_sha)
    correction = read(paths["correction"])
    imported = read(paths["import"])
    b_report = check_package_b(b_path, a_sha, correction, references)
    require(
        approved["status"] == "PACKAGE_A_SYNTHETIC_PASS_NOT_APPLIED"
        and approved["physical_pitches"] == 6,
        "Unexpected Package A scope.",
    )
    source = recovery_url(original, recovery_name)
    corrected = recovery_url(original, correction["candidate_database"])
    full = recovery_url(original, imported["candidate_database"])
    previous_path = backup / "release_rehearsal_01" / "release_manifest.json"
    require(
        sha(previous_path) == "907037191f5922b5021a45516f6350dc6a5233833f70eb3379e1ef5e1b6cae12",
        "Prior historical rehearsal manifest checksum differs.",
    )
    previous = read(previous_path)
    previous_public = recovery_url(original, previous["candidate_database"])
    expected = baseline["snapshot"]["local"]
    previous_tables = previous["candidate_fingerprint"]["tables"]
    require(
        previous["status"] == "REHEARSAL_PASS_NOT_PUBLISHED"
        and previous["production_write_allowed"] is False
        and previous["cohort"] == cohort
        and previous["source_fingerprint"] == expected
        and previous["reference_hashes"] == references,
        "Prior historical public rehearsal differs.",
    )
    require(
        integrity.fingerprint(source.render_as_string(hide_password=False), "local") == expected,
        "Recovered local historical source changed.",
    )
    require(
        integrity.fingerprint(previous_public.render_as_string(hide_password=False), "public")
        == previous["candidate_fingerprint"],
        "Prior public rehearsal changed.",
    )
    require(
        snapshot(corrected, SEASON) == correction["candidate_fingerprint"]
        and snapshot(full, SEASON) == imported["candidate_fingerprint"],
        "Corrected or imported candidate fingerprint changed.",
    )
    historical_ids = original_players(source, {})
    public_player_ids = original_players(previous_public, {})
    require(
        historical_fingerprint(full, historical_ids) == expected["tables"],
        "Historical rows changed in the full candidate.",
    )
    # Recompute the reference payload from the actual imported database.
    import gzip

    app = app_for(full)
    try:
        with app.app_context():
            coverage, start, through = physical_scope(SEASON)
            require(coverage == [1, 6, 6, 2], "Full candidate coverage changed.")
            payload = location_payload(SEASON, coverage, start, through)
            location = b_path.parent / b_report["entry"]["artifacts"]["location"]["file"]
            require(
                payload == json.loads(gzip.decompress(location.read_bytes())),
                "Location reference cannot be reproduced from the final candidate.",
            )
    finally:
        dispose(app)
    output.mkdir(parents=True, exist_ok=False)
    candidate = recovery_url(original, "mlb_release_candidate_" + uuid4().hex[:12])
    restored = recovery_url(original, "mlb_release_candidate_" + uuid4().hex[:12])
    clone_staging(full, candidate)
    require(snapshot(candidate, SEASON) == imported["candidate_fingerprint"], "Clone changed.")
    derive_future_cohort(full, candidate, cohort, [FIXTURE_PITCHER])
    require(
        historical_fingerprint(candidate, public_player_ids) == previous_tables,
        "Historical public rehearsal rows changed during future derivation.",
    )
    candidate_hash = snapshot(candidate, SEASON)
    print("HISTORICAL_FINGERPRINT_PASS", flush=True)
    old = audit_candidates(source, candidate, audit, cohort)
    require(old["status"] == "PASS", "Historical dashboard parity failed.")
    save(output / "historical_parity.json", old)
    new = audit_future(full, candidate)
    save(output / "future_parity.json", new)
    print("FUTURE_API_PARITY_PASS", flush=True)
    archive = output / "synthetic_public_candidate.dump"
    export_candidate(candidate, archive)
    archive_record = evidence(archive)
    restore_archive(restored, archive)
    require(snapshot(restored, SEASON) == candidate_hash, "Restored archive differs.")
    require(evidence(archive) == archive_record, "Archive changed during restore.")
    require(audit_future(candidate, restored) == new, "Restored dashboard differs.")
    print("ARCHIVE_RESTORE_PASS", flush=True)
    require(
        snapshot(candidate, SEASON) == candidate_hash
        and snapshot(full, SEASON) == imported["candidate_fingerprint"]
        and snapshot(corrected, SEASON) == correction["candidate_fingerprint"],
        "A sealed candidate changed.",
    )
    require(
        integrity.fingerprint(source.render_as_string(hide_password=False), "local") == expected
        and integrity.fingerprint(previous_public.render_as_string(hide_password=False), "public")
        == previous["candidate_fingerprint"]
        and integrity.reference_hashes() == references
        and sha(REGISTRY) == registry_sha
        and sha(a_path) == a_sha
        and sha(b_path) == b_sha
        and commit() == code,
        "Historical source, reference, evidence or code changed.",
    )
    input_paths(inputs, True)
    check_package_b(b_path, a_sha, correction, references)
    clean_checkout()
    manifest = {
        "schema": 1,
        "status": "PACKAGE_C_SYNTHETIC_PASS_NOT_PUBLISHED",
        "synthetic": True,
        "season": SEASON,
        "commit": code,
        "candidate_database": candidate.database,
        "restored_database": restored.database,
        "candidate_fingerprint": candidate_hash,
        "restored_fingerprint": candidate_hash,
        "historical_reference_hashes": references,
        "registry_sha256": registry_sha,
        "package_a_sha256": a_sha,
        "package_b_sha256": b_sha,
        "historical_public_rehearsal_fingerprint": previous_tables,
        "historical_cases": len(old["results"]),
        "future_cases": len(new["results"]),
        "artifacts": {
            name: evidence(output / name)
            for name in (
                "historical_parity.json",
                "future_parity.json",
                "synthetic_public_candidate.dump",
            )
        },
        "production_write_allowed": False,
        "publication_blockers": BLOCKERS,
    }
    save(output / "release_manifest.json", manifest)
    verify_manifest(output, sha(output / "release_manifest.json"))
    print(manifest["status"], flush=True)
    print("Manifest SHA-256:", sha(output / "release_manifest.json"), flush=True)
    print("No live database, registry or deployment changes performed.", flush=True)


def verify_manifest(output, expected_sha):
    path = output / "release_manifest.json"
    require(sha(path) == expected_sha, "Release manifest checksum mismatch.")
    report = read(path)
    require(
        report["schema"] == 1
        and report["status"] == "PACKAGE_C_SYNTHETIC_PASS_NOT_PUBLISHED"
        and report["synthetic"] is True
        and report["season"] == SEASON
        and report["production_write_allowed"] is False
        and report["publication_blockers"] == BLOCKERS
        and report["candidate_database"] != report["restored_database"]
        and report["candidate_fingerprint"] == report["restored_fingerprint"]
        and report["historical_cases"] == 660
        and report["future_cases"] == 2 * len(future_plan()),
        "Invalid synthetic release manifest.",
    )
    require(
        set(report["artifacts"])
        == {"historical_parity.json", "future_parity.json", "synthetic_public_candidate.dump"},
        "Invalid release artifact set.",
    )
    for name, record in report["artifacts"].items():
        require(evidence(output / name) == record, f"Release artifact changed: {name}")
    historical = read(output / "historical_parity.json")
    require(
        historical["status"] == "PASS"
        and not historical["index_differences"]
        and len(historical["results"]) == 660
        and len({(r["pitcher_id"], r["endpoint"], r["scope"]) for r in historical["results"]})
        == 660
        and all(r["status"] == "PASS" and not r["different_fields"] for r in historical["results"]),
        "Historical comparison evidence failed.",
    )
    future = read(output / "future_parity.json")
    expected = [
        {"scope": scope, "endpoint": endpoint, "pitches": n, "http": 200 if n else 404}
        for scope, _, n in future_plan()
        for endpoint in ("profile", "charts")
    ]
    require(future == {"status": "PASS", "results": expected}, "Future comparison evidence failed.")
    return report


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--synthetic-backup", type=Path)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--manifest-sha")
    args = parser.parse_args()
    try:
        require(
            bool(args.synthetic_backup) != bool(args.manifest_sha),
            "Choose synthetic rehearsal or checksum-pinned manifest review.",
        )
        if args.synthetic_backup:
            rehearse(args.synthetic_backup, args.output)
        else:
            verify_manifest(args.output, args.manifest_sha)
            print("PACKAGE_C_REVIEW_PASS_NO_PUBLICATION")
        return 0
    except Exception as exc:
        print("PACKAGE_C_FAILED:", str(exc) if isinstance(exc, ValueError) else type(exc).__name__)
        print("No publication attempted. Isolated databases and artifacts retained.")
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
