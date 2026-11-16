"""Export local records behind public/local pitcher profile differences.

Read-only and restricted to pitcher IDs present in a prior public parity audit.
The resulting two files include the pitch-level and independently published
FanGraphs inputs needed to diagnose the remaining profile differences.

    python -m scripts.export_parity_inputs --audit outputs/dashboard_parity_after_rv_refresh_2026.json

No credentials, connection strings, or unrelated MLB pitchers are exported.
"""

from __future__ import annotations

import argparse
import csv
import gzip
import json
import math
from datetime import date, datetime
from pathlib import Path

from dotenv import load_dotenv


def select_mismatched_pitchers(report, pitcher_id=None):
    """Check the audit and select only pitchers with unresolved differences."""
    if not isinstance(report, dict) or not isinstance(report.get("results"), list):
        raise ValueError("Expected a parity audit JSON with a results list.")
    season = report.get("season")
    if type(season) is not int or not 2015 <= season <= 2100:
        raise ValueError("The parity report is missing a valid season.")
    expected = {}
    for row in report["results"]:
        if row.get("error"):
            raise ValueError(f"Parity report contains a failed profile: {row['error']}")
        if not row.get("different_fields"):
            continue
        identifier = int(row["pitcher_id"])
        count = int(row["local_pitches"])
        if identifier in expected or count < 1 or count != int(row["public_pitches"]):
            raise ValueError(f"Duplicate or inconsistent audit record for {identifier}.")
        expected[identifier] = count
    if pitcher_id is not None:
        if pitcher_id not in expected:
            raise ValueError(f"Pitcher {pitcher_id} is not mismatched in the audit.")
        expected = {pitcher_id: expected[pitcher_id]}
    if not expected or len(expected) > 100:
        raise ValueError(f"Unexpected number of mismatched pitchers: {len(expected)}")
    return season, expected


def _csv_value(value):
    if value is None:
        return ""
    if isinstance(value, (date, datetime)):
        return value.isoformat()
    if isinstance(value, bool):
        return "true" if value else "false"
    if isinstance(value, float) and not math.isfinite(value):
        raise ValueError("Source contains an invalid nonfinite numeric value.")
    return value


def write_pitch_snapshot(rows, destination, columns, expected):
    """Stream local pitch inputs and fail rather than exporting a partial sample."""
    destination = Path(destination)
    destination.parent.mkdir(parents=True, exist_ok=True)
    counts = dict.fromkeys(expected, 0)
    seen = set()
    try:
        with gzip.open(destination, "wt", encoding="utf-8", newline="") as output:
            writer = csv.writer(output)
            writer.writerow(columns)
            for row in rows:
                identifier = int(row["pitcher_id"])
                pitch_id = row["pitch_id"]
                if identifier not in expected or pitch_id in seen:
                    raise ValueError("Unexpected pitcher or duplicate pitch in export.")
                seen.add(pitch_id)
                counts[identifier] += 1
                writer.writerow([_csv_value(row[column]) for column in columns])
        if counts != expected:
            raise ValueError(f"Local pitch counts have changed since audit: {counts}")
    except Exception:
        destination.unlink(missing_ok=True)
        raise
    return sum(counts.values())


def write_published_snapshot(rows, destination, columns):
    destination = Path(destination)
    destination.parent.mkdir(parents=True, exist_ok=True)
    count = 0
    with gzip.open(destination, "wt", encoding="utf-8", newline="") as output:
        writer = csv.writer(output)
        writer.writerow(columns)
        for row in rows:
            writer.writerow([_csv_value(row[column]) for column in columns])
            count += 1
    return count


def main():
    parser = argparse.ArgumentParser(
        description="Export only local 2026 records for the mismatched public pitcher profiles."
    )
    parser.add_argument("--audit", type=Path, required=True)
    parser.add_argument("--pitcher", type=int, help="Limit to one mismatched MLB pitcher ID")
    parser.add_argument("--output-dir", type=Path, default=Path("outputs"))
    args = parser.parse_args()
    report = json.loads(args.audit.read_text(encoding="utf-8"))
    season, expected = select_mismatched_pitchers(report, args.pitcher)
    load_dotenv()

    from sqlalchemy import select

    from app import create_app
    from app.extensions import db
    from app.models import FanGraphsStuff, Game, Pitch

    destination = args.output_dir
    pitch_path = destination / f"parity_source_pitches_{season}.csv.gz"
    fg_path = destination / f"parity_source_fangraphs_{season}.csv.gz"
    app = create_app()
    with app.app_context():
        pitch_fields = [column.name for column in Pitch.__table__.columns]
        pitch_fields.extend(["audit_game_date", "audit_season"])
        pitches = (
            db.session.execute(
                select(
                    *Pitch.__table__.columns,
                    Game.game_date.label("audit_game_date"),
                    Game.season.label("audit_season"),
                )
                .join(Game, Game.game_pk == Pitch.game_pk)
                .where(Game.season == season, Pitch.pitcher_id.in_(expected))
                .order_by(Pitch.pitcher_id, Pitch.pitch_id)
            )
            .mappings()
            .yield_per(2000)
        )
        pitch_count = write_pitch_snapshot(pitches, pitch_path, pitch_fields, expected)
        fg_fields = [column.name for column in FanGraphsStuff.__table__.columns]
        grades = (
            db.session.execute(
                select(*FanGraphsStuff.__table__.columns)
                .where(FanGraphsStuff.season == season, FanGraphsStuff.mlb_id.in_(expected))
                .order_by(FanGraphsStuff.mlb_id, FanGraphsStuff.category)
            )
            .mappings()
            .all()
        )
        grade_count = write_published_snapshot(grades, fg_path, fg_fields)
    print(f"Exported {pitch_count:,} pitch records for {len(expected)} mismatched pitchers.")
    print(f"Exported {grade_count:,} FanGraphs grade records.")
    print(f"Pitch snapshot: {pitch_path.resolve()}")
    print(f"FanGraphs snapshot: {fg_path.resolve()}")
    print("Read-only: no database records were changed.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
