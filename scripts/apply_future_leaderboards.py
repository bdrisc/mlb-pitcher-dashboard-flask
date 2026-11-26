"""Rehearse published metric inserts into a new quarantined synthetic candidate."""

from __future__ import annotations

import argparse
import hashlib
import os
from datetime import datetime, timezone
from pathlib import Path
from uuid import uuid4

from scripts import snapshot_integrity as integrity
from scripts.acquire_future_leaderboards import build_report, validate_correction
from scripts.apply_future_corrections import clone_staging, fingerprint, snapshot
from scripts.reconcile_future_sources import read_json, read_staged_sources
from scripts.rehearse_snapshot_release import (
    ReleaseError,
    assert_identity,
    clean_checkout,
    commit,
    connect,
    recovery_url,
    require,
    save,
    sha,
)

COLUMNS = {
    "fangraphs_stuff": (
        "mlb_id",
        "season",
        "category",
        "fangraphs_id",
        "stuff_plus",
        "location_plus",
        "pitching_plus",
    ),
    "published_pitching_metrics": (
        "mlb_id",
        "season",
        "batter_side",
        "fangraphs_id",
        "fip",
        "xfip",
        "siera",
        "xera",
    ),
    "savant_active_spin": ("mlb_id", "season", "pitch_type", "active_spin_pct"),
}


def approved_inputs(args):
    require(args.synthetic, "Real imports require independently reviewed identity and coverage.")
    stage, staged = read_staged_sources(args.staging_report, args.staging_sha)
    require(stage["synthetic"] is True, "Only synthetic rehearsals are enabled.")
    validate_correction(
        args.correction_report, args.correction_sha, stage, staged, args.staging_sha
    )
    correction = read_json(args.correction_report)
    require(sha(args.report) == args.report_sha, "Leaderboard report checksum mismatch.")
    report = read_json(args.report)
    rebuilt = build_report(
        stage,
        staged,
        args.report.parent / "raw",
        report["responses"],
        args.staging_sha,
        args.correction_sha,
    )
    require(report == rebuilt, "Leaderboard evidence replay differs.")
    require(
        report["synthetic"] is True
        and not report["missing_values"]
        and not report["unmapped_fangraphs_grades"]
        and not report["unmapped_fangraphs_rates"]
        and report["spin_season_in_response"]
        and all(
            not v["missing_staged_pitchers"] and not v["outside_staging_pitchers"]
            for v in report["coverage"].values()
        ),
        "Synthetic leaderboard coverage is incomplete.",
    )
    return stage, staged, correction, report


def mappings(pairs):
    by_mlb = {}
    by_fg = {}
    for pid, fg_id in pairs:
        if fg_id is None:
            continue
        require(
            str(fg_id).isdigit() and int(fg_id) > 0,
            "Invalid FanGraphs identity.",
        )
        fg_id = str(int(fg_id))
        require(
            by_mlb.get(pid, fg_id) == fg_id and by_fg.get(fg_id, pid) == pid,
            "Conflicting historical or planned FanGraphs identity.",
        )
        by_mlb[pid] = fg_id
        by_fg[fg_id] = pid
    return by_mlb


def planned_rows(report, pitcher_ids):
    result = {}
    for table, columns in COLUMNS.items():
        seen = set()
        rows = []
        for row in report[table]:
            require(
                set(row) == set(columns)
                and row["mlb_id"] in pitcher_ids
                and row["season"] == report["season"],
                "Unexpected metric row scope.",
            )
            values = tuple(row[c] for c in columns)
            key = values[:3]
            require(key not in seen, "Duplicate planned metric key.")
            seen.add(key)
            if table == "published_pitching_metrics":
                require(row["batter_side"] == "ALL", "Only overall rates are allowed.")
            rows.append(values)
        if report["synthetic"]:
            require(bool(rows), "Expected nonempty synthetic metric rows.")
        result[table] = sorted(rows, key=lambda row: row[:3])
    return result


def verify_identity(cur, season, staged, rows, reviewed_mapping=None):
    cur.execute(
        """
        SELECT p.pitch_id, p.pitcher_id, g.game_type
        FROM pitches p JOIN games g USING(game_pk) WHERE g.season = %s
        """,
        (season,),
    )
    expected = {key: (pid, "R") for pid, pitches in staged.items() for key in pitches}
    require(
        {key: (pid, kind) for key, pid, kind in cur} == expected,
        "Candidate pitch identities differ from approved staging.",
    )
    cur.execute("SELECT mlb_id FROM players WHERE mlb_id = ANY(%s)", (list(staged),))
    require({row[0] for row in cur} == set(staged), "Candidate player identities missing.")
    cur.execute(
        """
        SELECT DISTINCT mlb_id, fangraphs_id FROM fangraphs_stuff
        WHERE season <> %s
        UNION
        SELECT DISTINCT mlb_id, fangraphs_id FROM published_pitching_metrics
        WHERE season <> %s
        """,
        (season, season),
    )
    # Historical crosswalk rows outside the staged population matter too: a
    # proposed FG ID may already belong to a different MLB pitcher.
    planned = [
        (row[0], row[3])
        for table in ("fangraphs_stuff", "published_pitching_metrics")
        for row in rows[table]
        if row[3] is not None
    ]
    historical = list(cur)
    relevant_mlb = set(staged)
    planned_mapping = mappings(planned)
    relevant_fg = set(planned_mapping.values())
    relevant = [
        (pid, fg)
        for pid, fg in historical
        if pid in relevant_mlb
        or (fg is not None and str(fg).isdigit() and str(int(fg)) in relevant_fg)
    ]
    mapping = mappings(relevant + planned)
    if reviewed_mapping is None:
        require(set(staged) <= set(mapping), "Synthetic FanGraphs identity missing.")
        return {str(pid): mapping[pid] for pid in sorted(staged)}
    require(planned_mapping == reviewed_mapping, "Independent real identity mapping differs.")
    return {str(pid): mapping[pid] for pid in sorted(planned_mapping)}


def outside_fingerprint(conn, season):
    """Hash all non-target metric rows, including future years other than target."""
    result = {}
    for table in COLUMNS:
        digest = hashlib.sha256()
        count = 0
        order = integrity.TABLES[table]
        with conn.cursor(name="outside_metric_rows") as cur:
            cur.itersize = 4000
            cur.execute(
                f"SELECT encode(sha256(convert_to(to_jsonb(t)::text, 'UTF8')), 'hex') "
                f"FROM {table} t WHERE season <> %s ORDER BY {order}",
                (season,),
            )
            for (value,) in cur:
                digest.update(value.encode("ascii"))
                count += 1
        result[table] = {"rows": count, "sha256": digest.hexdigest()}
    return result


def insert_rows(cur, table, rows, now):
    if not rows:
        return
    columns = COLUMNS[table]
    if table == "published_pitching_metrics":
        columns += ("fangraphs_updated_at", "savant_updated_at")
        data = [
            (
                *row,
                now if any(v is not None for v in row[4:7]) else None,
                now if row[7] is not None else None,
            )
            for row in rows
        ]
    else:
        columns += ("updated_at",)
        data = [(*row, now) for row in rows]
    placeholders = ", ".join(["%s"] * len(columns))
    cur.executemany(f"INSERT INTO {table} ({', '.join(columns)}) VALUES ({placeholders})", data)
    require(cur.rowcount == len(rows), "Unexpected inserted row count.")


def apply_transaction(conn, database, staged, report, before, reviewed_mapping=None):
    season = report["season"]
    require(
        type(season) is int
        and season >= 2027
        and (
            (report["synthetic"] is True and reviewed_mapping is None)
            or (
                report["synthetic"] is False
                and bool(reviewed_mapping)
                and database.startswith("mlb_release_candidate_")
            )
        ),
        "Synthetic future scope or independently reviewed real scope required.",
    )
    rows = planned_rows(report, set(staged))
    with conn.cursor() as cur:
        cur.execute("SET TRANSACTION ISOLATION LEVEL REPEATABLE READ")
    assert_identity(conn, database)
    with conn.cursor() as cur:
        cur.execute(f"LOCK TABLE {', '.join(integrity.TABLES)} IN SHARE ROW EXCLUSIVE MODE")
    require(fingerprint(conn, season) == before, "Clone differs from corrected candidate.")
    untouched = outside_fingerprint(conn, season)
    now = datetime.now(timezone.utc)
    with conn.cursor() as cur:
        identities = verify_identity(cur, season, staged, rows, reviewed_mapping)
        for table in COLUMNS:
            cur.execute(f"SELECT count(*) FROM {table} WHERE season = %s", (season,))
            require(cur.fetchone()[0] == 0, "Target season already contains published metrics.")
        for table, values in rows.items():
            insert_rows(cur, table, values, now)
        for table, values in rows.items():
            columns = ", ".join(COLUMNS[table])
            cur.execute(f"SELECT {columns} FROM {table} WHERE season = %s", (season,))
            actual = sorted(cur.fetchall(), key=lambda row: row[:3])
            require(actual == values, "Stored published metrics differ from approved plan.")
    after = fingerprint(conn, season)
    require(
        all(after[table] == before[table] for table in before if table not in COLUMNS)
        and outside_fingerprint(conn, season) == untouched
        and all(after[t]["rows"] == before[t]["rows"] + len(rows[t]) for t in COLUMNS),
        "A row outside the approved import changed.",
    )
    return after, identities


def run(args):
    from dotenv import load_dotenv

    load_dotenv(integrity.ROOT / ".env")
    from app.config import database_url

    clean_checkout()
    code = commit()
    stage, staged, correction, report = approved_inputs(args)
    before = correction["candidate_fingerprint"]
    season = stage["season"]
    for key in list(os.environ):
        if key.upper().startswith("PG"):
            del os.environ[key]
    source = recovery_url(database_url(), correction["candidate_database"])
    target = recovery_url(database_url(), "mlb_release_candidate_" + uuid4().hex[:12])
    require(source.database.startswith("mlb_release_candidate_"), "Invalid corrected source.")
    references = integrity.reference_hashes()
    require(snapshot(source, season) == before, "Corrected source fingerprint changed.")
    args.output.mkdir(parents=True, exist_ok=False)
    clone_staging(source, target)
    print(f"Created isolated leaderboard candidate: {target.database}", flush=True)
    with connect(target) as conn:
        after, identities = apply_transaction(conn, target.database, staged, report, before)
    require(snapshot(target, season) == after, "Committed candidate fingerprint changed.")
    require(snapshot(source, season) == before, "Corrected source changed.")
    require(integrity.reference_hashes() == references, "Historical references changed.")
    require(commit() == code, "Code changed during import.")
    clean_checkout()
    require(
        approved_inputs(args) == (stage, staged, correction, report),
        "Approved evidence changed during import.",
    )
    counts = {table: len(report[table]) for table in COLUMNS}
    save(
        args.output / "leaderboard_import_report.json",
        {
            "schema": 1,
            "status": "LEADERBOARD_IMPORT_PASS_QUARANTINED",
            "season": season,
            "synthetic": True,
            "commit": code,
            "source_database": source.database,
            "candidate_database": target.database,
            "staging_report_sha256": args.staging_sha,
            "correction_report_sha256": args.correction_sha,
            "leaderboard_report_sha256": args.report_sha,
            "source_fingerprint": before,
            "candidate_fingerprint": after,
            "historical_fingerprint": correction["historical_fingerprint"],
            "synthetic_identity_mapping": identities,
            "inserted_rows": counts,
            "production_write_allowed": False,
            "real_identity_review_required": True,
            "release_blockers": correction["release_blockers"],
        },
    )
    print(counts)
    print("LEADERBOARD_IMPORT_PASS_QUARANTINED")
    print("Production publication remains blocked.")


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    for name in ("staging-report", "correction-report", "report", "output"):
        parser.add_argument("--" + name, required=True, type=Path)
    for name in ("staging-sha", "correction-sha", "report-sha"):
        parser.add_argument("--" + name, required=True)
    parser.add_argument("--synthetic", action="store_true")
    args = parser.parse_args()
    try:
        run(args)
        return 0
    except Exception as exc:
        message = (
            str(exc)
            if isinstance(exc, (ReleaseError, integrity.SnapshotError))
            else type(exc).__name__
        )
        print("LEADERBOARD_IMPORT_FAILED:", message)
        print("No publication attempted. Any isolated candidate remains quarantined.")
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
