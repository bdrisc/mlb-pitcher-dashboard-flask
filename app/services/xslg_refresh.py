"""Backfill official Statcast expected total bases from cached pitch-level exports.

Only the nullable expected slugging field is changed. Existing pitch histories,
run values, saved grades, and the pitcher pool are never overwritten.
"""

from __future__ import annotations

import csv
import gzip
from math import isfinite
from pathlib import Path

from sqlalchemy import bindparam, update

from app.extensions import db
from app.models import Pitch

COLUMN = "estimated_slg_using_speedangle"
REQUIRED = {"game_pk", "at_bat_number", "pitch_number", "pitcher", "events", COLUMN}
NOT_AT_BATS = {
    "walk",
    "intent_walk",
    "hit_by_pitch",
    "sac_fly",
    "sac_fly_double_play",
    "sac_bunt",
    "sac_bunt_double_play",
    "catcher_interf",
    "truncated_pa",
}


def _sources(paths):
    found = []
    for given in paths:
        path = Path(given).expanduser()
        if path.is_dir():
            found.extend(sorted(path.rglob("*.csv.gz")))
            found.extend(sorted(path.rglob("*.csv")))
        elif path.is_file():
            found.append(path)
        else:
            raise ValueError(f"xSLG source does not exist: {path}")
    return list(dict.fromkeys(path.resolve() for path in found))


def backfill_xslg(source_paths, *, season=None, batch_size=2000, progress=None):
    """Fill missing xSLG values for matching existing batted-ball pitches only."""
    if batch_size < 1:
        raise ValueError("batch_size must be positive.")
    sources = _sources(source_paths)
    if not sources:
        raise ValueError("No Statcast CSV or CSV.GZ source files found for xSLG backfill.")

    statement = (
        update(Pitch.__table__)
        .where(
            Pitch.__table__.c.pitch_id == bindparam("source_pitch_id"),
            Pitch.__table__.c.pitcher_id == bindparam("source_pitcher_id"),
            Pitch.__table__.c.events == bindparam("source_event"),
            Pitch.__table__.c.estimated_slg.is_(None),
        )
        .values(estimated_slg=bindparam("source_xslg"))
    )
    summary = {
        "files": 0,
        "files_without_xslg": 0,
        "scored_source_events": 0,
        "updated_pitches": 0,
    }

    def save(batch):
        if not batch:
            return
        result = db.session.execute(statement, batch)
        db.session.commit()
        summary["updated_pitches"] += max(0, result.rowcount or 0)

    for source in sources:
        opener = gzip.open if source.name.endswith(".gz") else open
        with opener(source, "rt", newline="", encoding="utf-8-sig") as stream:
            reader = csv.DictReader(stream)
            if not reader.fieldnames or COLUMN not in reader.fieldnames:
                summary["files_without_xslg"] += 1
                if progress:
                    progress(f"xSLG skipped {source.name}: column absent.")
                continue
            missing = REQUIRED - set(reader.fieldnames)
            if missing:
                raise ValueError(f"{source.name}: missing required columns {sorted(missing)}.")

            batch = []
            source_events = 0
            for row in reader:
                event = (row["events"] or "").strip().lower()
                raw_value = (row[COLUMN] or "").strip()
                if not raw_value or not event or event in NOT_AT_BATS:
                    continue
                if season is not None:
                    game_date = row.get("game_date", "")
                    if not game_date or str(game_date)[:4] != str(season):
                        continue
                value = float(raw_value)
                if not isfinite(value) or not 0 <= value <= 4:
                    raise ValueError(f"{source.name}: invalid expected bases {raw_value!r}.")
                identity = "_".join(
                    (row["game_pk"], row["at_bat_number"], row["pitch_number"])
                )
                batch.append(
                    {
                        "source_pitch_id": identity,
                        "source_pitcher_id": int(row["pitcher"]),
                        "source_event": row["events"],
                        "source_xslg": value,
                    }
                )
                source_events += 1
                if len(batch) >= batch_size:
                    save(batch)
                    batch.clear()
            save(batch)
            summary["files"] += 1
            summary["scored_source_events"] += source_events
            if progress:
                progress(f"xSLG {source.name}: {source_events:,} source batted balls scanned.")
    if not summary["files"]:
        raise ValueError(
            "No input file contains estimated_slg_using_speedangle. "
            "Use a newer Baseball Savant Statcast export; existing data were preserved."
        )
    return summary
