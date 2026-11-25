"""Build a quarantined future-season candidate, never a publishable release."""

from __future__ import annotations

import argparse
import csv
import hashlib
import json
import os
import shutil
from pathlib import Path
from uuid import uuid4

from scripts import snapshot_integrity as integrity
from scripts.audit_future_statcast_sources import scan
from scripts.rehearse_snapshot_release import (
    ReleaseError,
    assert_identity,
    clean_checkout,
    clone_candidate,
    commit,
    connect,
    evidence,
    recovery_url,
    require,
    reviewed_inputs,
    save,
    sha,
)

BLOCKERS = [
    "independent pitch and completed-game source coverage",
    "official context-neutral run value aggregate verification",
    "official wOBA numerator and denominator verification",
    "reviewed player identity and throwing-hand reconciliation",
    "published FanGraphs and Savant season snapshots",
    "future-season reference validation and parity",
    "candidate recovery and explicit publication approval",
]


def verified_sources(paths, schedule, manifest, manifest_sha, season, destination):
    require(sha(manifest) == manifest_sha, "Source manifest checksum mismatch.")
    approved = json.loads(manifest.read_bytes())
    require(len({p.name for p in paths}) == len(paths), "Repeated source basename.")
    require(evidence(schedule) == approved["schedule"], "Schedule changed.")
    expected = {int(k): v for k, v in json.loads(schedule.read_bytes()).items()}
    actual = scan(paths, season, expected)
    actual["schedule"] = evidence(schedule)
    require(actual == approved, "Source files differ from reviewed preflight.")
    destination.mkdir()
    copies = []
    for path, record in zip(paths, actual["sources"], strict=True):
        target = destination / path.name
        with path.open("rb") as src, target.open("xb") as out:
            shutil.copyfileobj(src, out)
        require(
            evidence(target) == {k: record[k] for k in ("bytes", "sha256")},
            "Source changed during staging copy.",
        )
        copies.append(target)
    return actual, expected, copies


def historical_fingerprint(url, player_ids):
    """Reproduce the sealed table fingerprints for the original historical rows."""
    conditions = {
        "players": ("WHERE mlb_id = ANY(%s)", (player_ids,)),
        "games": ("WHERE season < 2027", ()),
        "pitches": (
            "WHERE game_pk IN (SELECT game_pk FROM games WHERE season < 2027)",
            (),
        ),
        "fangraphs_stuff": ("WHERE season < 2027", ()),
        "published_pitching_metrics": ("WHERE season < 2027", ()),
        "savant_active_spin": ("WHERE season < 2027", ()),
        "alembic_version": ("", ()),
    }
    tables = {}
    with connect(url) as conn:
        with conn.cursor() as cur:
            cur.execute("SET TRANSACTION ISOLATION LEVEL REPEATABLE READ READ ONLY")
        assert_identity(conn, url.database)
        with conn.cursor() as cur:
            cur.execute("SET LOCAL TIME ZONE 'UTC'")
            cur.execute("SET LOCAL extra_float_digits = 3")
        for table, order in integrity.TABLES.items():
            clause, params = conditions[table]
            digest = hashlib.sha256()
            count = 0
            with conn.cursor(name="historical_rows") as cur:
                cur.itersize = 4000
                cur.execute(
                    f"SELECT encode(sha256(convert_to(to_jsonb(t)::text, 'UTF8')), "
                    f"'hex') FROM {table} t {clause} ORDER BY {order}",
                    params,
                )
                for (row_hash,) in cur:
                    digest.update(row_hash.encode("ascii"))
                    count += 1
            tables[table] = {"rows": count, "sha256": digest.hexdigest()}
    return tables


def original_players(url, expected_games):
    with connect(url) as conn:
        assert_identity(conn, url.database)
        with conn.cursor() as cur:
            cur.execute(
                "SELECT count(*) FROM games WHERE game_pk = ANY(%s)", (list(expected_games),)
            )
            require(cur.fetchone()[0] == 0, "Source game IDs overlap the sealed snapshot.")
            cur.execute("SELECT count(*) FROM games WHERE season >= 2027")
            require(cur.fetchone()[0] == 0, "Expected an exclusively historical source.")
            cur.execute("SELECT mlb_id FROM players ORDER BY mlb_id")
            return [row[0] for row in cur]


def synthetic_sources(output):
    """Create clearly synthetic records to exercise the real staging path."""
    fields = [
        "game_date",
        "game_pk",
        "game_type",
        "at_bat_number",
        "pitch_number",
        "pitch_type",
        "player_name",
        "pitcher",
        "batter",
        "stand",
        "p_throws",
        "balls",
        "strikes",
        "description",
        "type",
        "home_team",
        "away_team",
        "inning",
        "inning_topbot",
        "zone",
        "release_speed",
        "release_spin_rate",
        "spin_axis",
        "pfx_x",
        "pfx_z",
        "plate_x",
        "plate_z",
        "sz_top",
        "sz_bot",
        "release_pos_x",
        "vx0",
        "vy0",
        "vz0",
        "ax",
        "ay",
        "az",
        "events",
        "bb_type",
        "launch_speed",
        "launch_speed_angle",
        "estimated_ba_using_speedangle",
        "estimated_slg_using_speedangle",
        "estimated_woba_using_speedangle",
        "delta_run_exp",
    ]
    paths = []
    schedule = {}
    for offset in (1, 2):
        game = 2000000000 + offset
        day = f"2027-04-0{offset}"
        schedule[game] = day
        path = output / f"synthetic_{offset}.csv"
        with path.open("x", encoding="utf-8", newline="") as handle:
            writer = csv.DictWriter(handle, fieldnames=fields)
            writer.writeheader()
            common = {
                "game_date": day,
                "game_pk": game,
                "game_type": "R",
                "at_bat_number": 1,
                "pitch_type": "FF",
                "player_name": "Fixture, Pitcher",
                "pitcher": 2000000010,
                "batter": 2000000011,
                "stand": "R",
                "p_throws": "R",
                "balls": 0,
                "home_team": "BOS",
                "away_team": "NYY",
                "inning": 1,
                "inning_topbot": "Top",
                "release_speed": 95,
                "release_spin_rate": 2400,
                "spin_axis": 210,
                "pfx_x": -0.7,
                "pfx_z": 1.4,
                "plate_x": 0.1,
                "plate_z": 2.5,
                "sz_top": 3.5,
                "sz_bot": 1.5,
                "release_pos_x": -2,
                "vx0": 5,
                "vy0": -135,
                "vz0": -4,
                "ax": -10,
                "ay": 30,
                "az": -15,
            }
            writer.writerow(
                {
                    **common,
                    "pitch_number": 1,
                    "strikes": 0,
                    "description": "called_strike",
                    "type": "S",
                    "zone": 5,
                    "delta_run_exp": -0.04,
                }
            )
            writer.writerow(
                {
                    **common,
                    "pitch_number": 2,
                    "strikes": 1,
                    "description": "foul_tip",
                    "type": "S",
                    "zone": 14,
                    "delta_run_exp": -0.05,
                }
            )
            writer.writerow(
                {
                    **common,
                    "pitch_number": 3,
                    "strikes": 2,
                    "description": "hit_into_play",
                    "type": "X",
                    "zone": 5,
                    "events": "single",
                    "bb_type": "line_drive",
                    "launch_speed": 101,
                    "launch_speed_angle": 4,
                    "estimated_ba_using_speedangle": 0.6,
                    "estimated_slg_using_speedangle": 0.9,
                    "estimated_woba_using_speedangle": 0.55,
                    "delta_run_exp": 0.4,
                }
            )
        paths.append(path)
    schedule_path = output / "synthetic_schedule.json"
    save(schedule_path, schedule)
    manifest = scan(paths, 2027, schedule)
    manifest["schedule"] = evidence(schedule_path)
    manifest_path = output / "synthetic_source_manifest.json"
    save(manifest_path, manifest)
    return paths, schedule_path, manifest_path, sha(manifest_path)


def stage_files(target, paths, manifest, season, player_ids):
    from app import create_app
    from app.extensions import db
    from app.services.statcast_ingestion import ingest_statcast_file

    require(target.database.startswith("mlb_release_candidate_"), "Not a staging database.")
    with connect(target) as conn:
        assert_identity(conn, target.database)
    app = create_app(
        {
            "TESTING": True,
            "APP_ENV": "test",
            "SQLALCHEMY_DATABASE_URI": target.render_as_string(hide_password=False),
            "PITCH_DATA_PATH": str(integrity.ROOT / "data" / "sample_statcast.csv"),
        }
    )
    reports = []
    with app.app_context():
        try:
            require(
                db.engine.url.database == target.database and db.engine.url.host == target.host,
                "Application database target mismatch.",
            )
            for path, expected in zip(paths, manifest["sources"], strict=True):
                before = evidence(path)
                require(
                    before == {k: expected[k] for k in ("bytes", "sha256")},
                    "Staging source checksum mismatch.",
                )
                report = ingest_statcast_file(
                    path, frozen_player_ids=frozenset(player_ids), insert_only_season=season
                )
                require(
                    report.source_rows == report.inserted_rows == expected["rows"]
                    and report.updated_rows == report.rejected_rows == 0
                    and evidence(path) == before,
                    "Unexpected ingestion counts or source change.",
                )
                reports.append(
                    {"file": path.name, "rows": report.inserted_rows, "sha256": before["sha256"]}
                )
                print(f"STAGED_FILE_PASS: {path.name} ({report.inserted_rows:,} rows)", flush=True)
        finally:
            db.session.remove()
            db.engine.dispose()
    return reports


def verify_new_rows(target, paths, season, manifest, schedule):
    """Check persisted identities and values against transformed source records."""
    from psycopg import sql

    from app.services.statcast_ingestion import (
        CSV_READ_CHUNK_SIZE,
        _csv_columns,
        _iter_statcast_csv,
        _pitch_records,
        clean_statcast,
    )

    coverage = {}
    seen = set()
    with connect(target) as conn:
        with conn.cursor() as cur:
            cur.execute("SET TRANSACTION ISOLATION LEVEL REPEATABLE READ READ ONLY")
        assert_identity(conn, target.database)
        with conn.cursor() as cur:
            cur.execute("SELECT game_pk, game_date FROM games WHERE season = %s", (season,))
            require(
                {game: day.isoformat() for game, day in cur} == schedule,
                "Staged games differ from schedule.",
            )
            cur.execute(
                """
                SELECT count(*), count(DISTINCT p.pitcher_id), count(DISTINCT p.game_pk),
                       count(DISTINCT (p.game_pk,p.at_bat_number,p.pitch_number)),
                       count(p.delta_run_expectancy), count(p.spin_axis),
                       count(p.vaa), count(p.haa), count(p.vaa_adj), count(p.haaaa),
                       count(*) FILTER (WHERE p.is_whiff),
                       count(*) FILTER (WHERE p.is_strike),
                       count(*) FILTER (WHERE p.is_hard_hit)
                FROM pitches p JOIN games g USING(game_pk) WHERE g.season = %s
                """,
                (season,),
            )
            labels = (
                "rows",
                "pitchers",
                "games",
                "natural_keys",
                "rv_present",
                "spin_axis_present",
                "vaa_present",
                "haa_present",
                "vaa_adj_present",
                "haaaa_present",
                "whiffs",
                "strikes",
                "hard_hits",
            )
            coverage = dict(zip(labels, cur.fetchone(), strict=True))
            require(
                all(coverage[k] == manifest[k] for k in ("rows", "pitchers", "games"))
                and coverage["natural_keys"] == manifest["rows"],
                "Staged pitch coverage mismatch.",
            )
            for path in paths:
                for chunk in _iter_statcast_csv(path, _csv_columns(path), CSV_READ_CHUNK_SIZE):
                    records = _pitch_records(clean_statcast(chunk))
                    for start in range(0, len(records), 1000):
                        batch = records[start : start + 1000]
                        ids = [r["pitch_id"] for r in batch]
                        fields = sorted(batch[0])
                        cur.execute(
                            sql.SQL("SELECT {} FROM pitches WHERE pitch_id = ANY(%s)").format(
                                sql.SQL(", ").join(map(sql.Identifier, fields))
                            ),
                            (ids,),
                        )
                        actual = {
                            row[fields.index("pitch_id")]: dict(zip(fields, row, strict=True))
                            for row in cur
                        }
                        require(len(actual) == len(batch), "Missing persisted pitch IDs.")
                        for expected in batch:
                            key = expected["pitch_id"]
                            require(key not in seen, "Duplicate staged pitch identity.")
                            require(
                                actual[key] == expected, f"Stored pitch differs from source: {key}"
                            )
                            seen.add(key)
            require(len(seen) == coverage["rows"], "Incomplete pitch comparison.")
    return coverage


def run(args):
    from dotenv import load_dotenv

    load_dotenv(integrity.ROOT / ".env")
    from app.config import database_url

    clean_checkout()
    code = commit()
    baseline, _, _, source_name = reviewed_inputs(
        args.baseline, args.audit, args.backups, args.local_recovery, args.public_recovery
    )
    for key in list(os.environ):
        if key.upper().startswith("PG"):
            del os.environ[key]
    source = recovery_url(database_url(), source_name)
    target = recovery_url(database_url(), "mlb_release_candidate_" + uuid4().hex[:12])
    expected = baseline["snapshot"]["local"]
    source_url = source.render_as_string(hide_password=False)
    target_url = target.render_as_string(hide_password=False)
    require(integrity.fingerprint(source_url, "local") == expected, "Source fingerprint changed.")
    args.output.mkdir(parents=True, exist_ok=False)
    if args.synthetic:
        paths, schedule_path, manifest_path, digest = synthetic_sources(args.output)
    else:
        paths, schedule_path, manifest_path, digest = (
            args.sources,
            args.schedule,
            args.manifest,
            args.manifest_sha,
        )
    manifest, schedule, copies = verified_sources(
        paths, schedule_path, manifest_path, digest, args.season, args.output / "sources"
    )
    players = original_players(source, schedule)
    clone_candidate(source, target)
    print(f"Created isolated staging database: {target.database}", flush=True)
    require(integrity.fingerprint(target_url, "local") == expected, "Clone fingerprint mismatch.")
    reports = stage_files(target, copies, manifest, args.season, players)
    coverage = verify_new_rows(target, copies, args.season, manifest, schedule)
    require(
        historical_fingerprint(target, players) == expected["tables"],
        "Historical rows changed inside the staging candidate.",
    )
    require(integrity.fingerprint(source_url, "local") == expected, "Recovered source changed.")
    require(
        integrity.reference_hashes() == baseline["snapshot"]["references"],
        "Historical references changed.",
    )
    require(commit() == code, "Code changed during staging.")
    clean_checkout()
    require(
        all(
            evidence(path) == {k: row[k] for k in ("bytes", "sha256")}
            for path, row in zip(copies, manifest["sources"], strict=True)
        ),
        "Staged source changed during verification.",
    )
    report = {
        "schema": 1,
        "status": "STAGING_PASS_QUARANTINED",
        "synthetic": args.synthetic,
        "season": args.season,
        "commit": code,
        "candidate_database": target.database,
        "historical_fingerprint": expected,
        "source_manifest": manifest,
        "source_manifest_sha256": digest,
        "ingestion": reports,
        "coverage": coverage,
        "source_values_matched": coverage["rows"],
        "release_blockers": BLOCKERS,
        "production_write_allowed": False,
    }
    save(args.output / "staging_report.json", report)
    print(json.dumps(coverage, indent=2))
    print("STAGING_PASS_QUARANTINED")
    print("Production publication remains blocked.")


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    for name in ("baseline", "audit", "backups", "local-recovery", "public-recovery", "output"):
        parser.add_argument("--" + name, type=Path, required=True)
    parser.add_argument("--season", type=int, default=2027)
    parser.add_argument("--synthetic", action="store_true")
    parser.add_argument("--schedule", type=Path)
    parser.add_argument("--manifest", type=Path)
    parser.add_argument("--manifest-sha")
    parser.add_argument("sources", nargs="*", type=Path)
    args = parser.parse_args()
    inputs = (args.schedule, args.manifest, args.manifest_sha, args.sources)
    if args.synthetic:
        if any(inputs) or args.season != 2027:
            parser.error("Synthetic rehearsal accepts no source overrides and uses 2027.")
    elif not all(inputs) or args.season < 2027:
        parser.error(
            "Provide a reviewed future source manifest, digest, schedule and source files."
        )
    try:
        run(args)
    except Exception as exc:
        message = (
            str(exc)
            if isinstance(exc, (ReleaseError, integrity.SnapshotError))
            else type(exc).__name__
        )
        print("STAGING_FAILED:", message)
        print("No publication attempted. Isolated candidates and evidence retained.")
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
