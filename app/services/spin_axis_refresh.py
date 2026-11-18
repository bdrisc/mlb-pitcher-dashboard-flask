"""Backfill official Savant spin_axis without re-ingesting or changing pitch history."""

from __future__ import annotations

import csv
import gzip
from math import isfinite
from pathlib import Path

from sqlalchemy import bindparam, update

from app.extensions import db
from app.models import Pitch

REQUIRED = {"game_pk", "at_bat_number", "pitch_number", "pitcher", "spin_axis"}


def _sources(paths):
    sources = []
    for supplied in paths:
        path = Path(supplied).expanduser()
        if path.is_dir():
            sources.extend(sorted(path.rglob("*.csv.gz")))
            sources.extend(sorted(path.rglob("*.csv")))
        elif path.is_file():
            sources.append(path)
        else:
            raise ValueError(f"Spin-axis source does not exist: {path}")
    return list(dict.fromkeys(path.resolve() for path in sources))


def backfill_spin_axis(source_paths, *, season=None, batch_size=2000, progress=None):
    """Fill missing official spin axes for existing matching pitcher/pitch IDs."""
    if batch_size < 1:
        raise ValueError("batch_size must be positive.")
    sources = _sources(source_paths)
    if not sources:
        raise ValueError("No Statcast CSV or CSV.GZ source files found for spin-axis backfill.")

    statement = (
        update(Pitch.__table__)
        .where(
            Pitch.__table__.c.pitch_id == bindparam("source_pitch_id"),
            Pitch.__table__.c.pitcher_id == bindparam("source_pitcher_id"),
            Pitch.__table__.c.spin_axis.is_(None),
        )
        .values(spin_axis=bindparam("source_axis"))
    )
    summary = {
        "files": 0,
        "files_without_spin_axis": 0,
        "tracked_source_pitches": 0,
        "updated_pitches": 0,
    }

    def write(batch):
        if not batch:
            return
        result = db.session.execute(statement, batch)
        db.session.commit()
        summary["updated_pitches"] += max(0, result.rowcount or 0)

    for source in sources:
        opener = gzip.open if source.name.endswith(".gz") else open
        with opener(source, "rt", newline="", encoding="utf-8-sig") as stream:
            reader = csv.DictReader(stream)
            if not reader.fieldnames or "spin_axis" not in reader.fieldnames:
                summary["files_without_spin_axis"] += 1
                if progress:
                    progress(f"Spin axis skipped {source.name}: no spin_axis column.")
                continue
            missing = REQUIRED - set(reader.fieldnames)
            if missing:
                raise ValueError(f"{source.name}: missing required columns {sorted(missing)}.")

            batch = []
            for row in reader:
                raw_axis = (row["spin_axis"] or "").strip()
                if not raw_axis:
                    continue
                if season is not None and str(row.get("game_date", ""))[:4] != str(season):
                    continue
                if (row.get("description") or "").lower() in (
                    "automatic_ball",
                    "automatic_strike",
                ):
                    continue
                try:
                    value = float(raw_axis)
                except ValueError as exc:
                    raise ValueError(f"{source.name}: invalid spin axis {raw_axis!r}.") from exc
                if not isfinite(value) or not 0 <= value <= 360:
                    raise ValueError(f"{source.name}: spin axis must be 0–360°, got {raw_axis!r}.")

                batch.append(
                    {
                        "source_pitch_id": "_".join(
                            (row["game_pk"], row["at_bat_number"], row["pitch_number"])
                        ),
                        "source_pitcher_id": int(row["pitcher"]),
                        "source_axis": value,
                    }
                )
                summary["tracked_source_pitches"] += 1
                if len(batch) >= batch_size:
                    write(batch)
                    batch.clear()
            write(batch)
            summary["files"] += 1
            if progress:
                progress(f"Spin axis scanned {source.name}.")

    if not summary["files"]:
        raise ValueError(
            "No input file contains spin_axis. Supply an official Baseball Savant "
            "Statcast export with that column; existing records were preserved."
        )
    return summary
