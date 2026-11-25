"""Read-only seal/verification of the reviewed 2026 dashboard snapshot."""

from __future__ import annotations

import argparse
import hashlib
import json
import subprocess
from getpass import getpass
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
REPORT_SHA = "0925d2a8ab19fbbdd67f897df8ccd07d71194ee0661c9f84d01e054cd06b790e"
COVERAGE = {"local": [868, 714114, 714114, 2429], "public": [50, 142141, 142141, 1304]}
TABLES = {
    "players": "mlb_id",
    "games": "game_pk",
    "pitches": 'pitch_id COLLATE "C"',
    "fangraphs_stuff": 'mlb_id, season, category COLLATE "C"',
    "published_pitching_metrics": 'mlb_id, season, batter_side COLLATE "C"',
    "savant_active_spin": 'mlb_id, season, pitch_type COLLATE "C"',
    "alembic_version": 'version_num COLLATE "C"',
}
ROLE_2025_SHA = "1bfc3e33b9e9b629e90f6eada1038887eea36a71a698317df710fb3b068013fd"
ROLE_2026_SHA = "23aea893b98db8cab6fdc7434dc7bce9a911f35f1358780c5e633904c9c153c5"
LOCATION_SHA = "eb09bc3ce164730186ce699c7c3443150a8339626dff1775ec6639b8a9d3ec99"
MOVEMENT_SHA = "afcfc905ce8aadac1ce08edc9dad418b06a4b964faf12f89eb181f52977acb20"
REFERENCES = {
    "league_pitch_roles_2025.json": ROLE_2025_SHA,
    "league_pitch_roles_2026.json": ROLE_2026_SHA,
    "league_location_2026.json.gz": LOCATION_SHA,
    "league_movement_2026.b85": MOVEMENT_SHA,
}


class SnapshotError(ValueError):
    """Safe diagnostic for a rejected snapshot."""


def file_digest(path):
    raw = path.read_bytes()
    if path.suffix != ".gz":
        raw = raw.replace(b"\r\n", b"\n")
    return hashlib.sha256(raw).hexdigest()


def validate_report(path):
    """Only seal the exact independently reviewed passing audit."""
    if file_digest(path) != REPORT_SHA:
        raise SnapshotError("Audit differs from the reviewed 660-comparison report.")
    report = json.loads(path.read_bytes())
    if report["status"] != "PASS" or len(report["results"]) != 660:
        raise SnapshotError("Extended audit did not pass.")
    return REPORT_SHA


def reference_hashes():
    found = {name: file_digest(ROOT / "data" / name) for name in REFERENCES}
    if found != REFERENCES:
        raise SnapshotError("Reviewed league reference checksum mismatch.")
    for name in ("vaa_adj_reference_2025.json", "haaaa_reference_2025.json"):
        found[name] = file_digest(ROOT / "data" / name)
    return found


def fingerprint(url, environment):
    """Hash all model data in one consistent, read-only PostgreSQL transaction."""
    import psycopg
    from sqlalchemy.engine import make_url

    parsed = make_url(url)
    if parsed.get_backend_name() not in ("postgresql", "postgres"):
        raise SnapshotError("Expected a PostgreSQL connection.")
    dsn = parsed.set(drivername="postgresql").render_as_string(hide_password=False)
    with psycopg.connect(dsn) as conn:
        with conn.cursor() as cur:
            cur.execute("SET TRANSACTION ISOLATION LEVEL REPEATABLE READ READ ONLY")
            cur.execute("SET LOCAL TIME ZONE 'UTC'")
            cur.execute("SET LOCAL extra_float_digits = 3")
            cur.execute(
                """
                SELECT count(DISTINCT p.pitcher_id), count(*),
                       count(DISTINCT (p.game_pk, p.at_bat_number, p.pitch_number)),
                       count(DISTINCT p.game_pk)
                FROM pitches p JOIN games g ON g.game_pk = p.game_pk
                WHERE g.season = 2026
                """
            )
            coverage = list(cur.fetchone())
            if coverage != COVERAGE[environment]:
                raise SnapshotError(f"{environment}: unexpected 2026 coverage {coverage}")
            cur.execute(
                """
                SELECT g.game_type, count(*) FROM pitches p
                JOIN games g ON g.game_pk = p.game_pk
                WHERE g.season = 2026 GROUP BY g.game_type
                """
            )
            if cur.fetchall() != [("R", coverage[1])]:
                raise SnapshotError(f"{environment}: unexpected game types")
        tables = {}
        for table, order in TABLES.items():
            digest = hashlib.sha256()
            count = 0
            # Names and order expressions are fixed module constants, not user inputs.
            with conn.cursor(name="snapshot_rows") as cur:
                cur.itersize = 4000
                cur.execute(
                    f"SELECT encode(sha256(convert_to(to_jsonb(t)::text, 'UTF8')), "
                    f"'hex') FROM {table} t ORDER BY {order}"
                )
                for (row_hash,) in cur:
                    digest.update(row_hash.encode("ascii"))
                    count += 1
            tables[table] = {"rows": count, "sha256": digest.hexdigest()}
            print(f"{environment}: {table}: {count:,} rows", flush=True)
    return {"coverage_2026": coverage, "tables": tables}


def collect():
    from dotenv import load_dotenv

    load_dotenv()
    from app.config import database_url

    references = reference_hashes()
    local = fingerprint(database_url(), "local")
    public_url = getpass("Production Neon PostgreSQL URL (hidden): ")
    public = fingerprint(public_url, "public")
    return {"schema": 1, "references": references, "local": local, "public": public}


def differences(expected, actual):
    return sorted(
        key for key in expected.keys() | actual.keys() if expected.get(key) != actual.get(key)
    )


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("mode", choices=("capture", "verify"))
    parser.add_argument("--baseline", type=Path, required=True)
    parser.add_argument("--report", type=Path)
    args = parser.parse_args()
    try:
        if args.mode == "capture":
            if not args.report or args.baseline.exists():
                raise SnapshotError("Capture requires --report and a new baseline path.")
            audit_sha = validate_report(args.report)
            snapshot = collect()
            baseline = {
                "audit_sha256": audit_sha,
                "capture_commit": subprocess.check_output(
                    ["git", "rev-parse", "HEAD"], cwd=ROOT, text=True
                ).strip(),
                "snapshot": snapshot,
            }
            args.baseline.parent.mkdir(parents=True, exist_ok=True)
            with args.baseline.open("x", encoding="utf-8") as handle:
                json.dump(baseline, handle, indent=2)
            print("SNAPSHOT_CAPTURE_PASS")
        else:
            baseline = json.loads(args.baseline.read_bytes())
            if baseline["audit_sha256"] != REPORT_SHA or baseline["snapshot"]["schema"] != 1:
                raise SnapshotError("Unsupported or unreviewed baseline.")
            changed = differences(baseline["snapshot"], collect())
            if changed:
                print("SNAPSHOT_DRIFT: " + ", ".join(changed))
                return 1
            print("SNAPSHOT_VERIFY_PASS")
        return 0
    except Exception as exc:
        # Do not echo database connection strings or driver error details.
        message = str(exc) if isinstance(exc, SnapshotError) else type(exc).__name__
        print("SNAPSHOT_CHECK_FAILED: " + message)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
