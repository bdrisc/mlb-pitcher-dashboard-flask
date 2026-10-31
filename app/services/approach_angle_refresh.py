"""Backfill only trajectory/approach fields on existing, unprocessed pitches."""

from __future__ import annotations

import io
from concurrent.futures import FIRST_COMPLETED, ThreadPoolExecutor, wait
from pathlib import Path

import pandas as pd
from sqlalchemy import func, or_, select, update

from app.extensions import db
from app.models import Game, Pitch
from app.services.approach_angles import ANGLE_VERSION, TRAJECTORY_FIELDS, trajectory_record
from app.services.run_value_refresh import _download

IDENTITY_FIELDS = ("game_pk", "at_bat_number", "pitch_number")
SOURCE_FIELDS = (*IDENTITY_FIELDS, "pitcher", "game_year", *TRAJECTORY_FIELDS, "p_throws")


def _source_records(frame):
    missing = (set(SOURCE_FIELDS) - {"p_throws"}) - set(frame.columns)
    if missing:
        raise ValueError("Trajectory source is missing columns: " + ", ".join(sorted(missing)))
    for key in set(SOURCE_FIELDS) - {"p_throws"}:
        frame[key] = pd.to_numeric(frame[key], errors="raise")
    identity = frame[list(IDENTITY_FIELDS)]
    if identity.isna().any().any() or identity.duplicated().any():
        raise ValueError("Source pitch identities are missing or duplicated.")
    for key in (*IDENTITY_FIELDS, "pitcher", "game_year"):
        if frame[key].isna().any() or (frame[key] % 1 != 0).any():
            raise ValueError("Source pitch identities and seasons must be integers.")
    records = {}
    for row in frame.to_dict(orient="records"):
        key = "_".join(str(int(row[field])) for field in IDENTITY_FIELDS)
        record = trajectory_record(row, checked=True)
        if row.get("p_throws") in ("R", "L"):
            record["pitcher_throws"] = row["p_throws"]
        records[key] = (
            int(row["pitcher"]),
            int(row["game_year"]),
            record,
        )
    return records


def fetch_trajectory_values(job):
    pid, season, first, last = job
    payload = _download(
        "/statcast_search/csv",
        {
            "player_type": "pitcher",
            "pitchers_lookup[]": pid,
            "hfSea": f"{season}|",
            "hfGT": "R|PO|S|A|",
            "game_date_gt": first.isoformat(),
            "game_date_lt": last.isoformat(),
            "min_pitches": 0,
            "min_results": 0,
            "type": "details",
            "all": "true",
        },
    )
    frame = pd.read_csv(io.BytesIO(payload), usecols=lambda c: c in SOURCE_FIELDS)
    if len(frame) >= 30000:
        raise ValueError("Savant response may be truncated; existing values preserved.")
    records = _source_records(frame)
    if any(owner != pid or year != season for owner, year, _ in records.values()):
        raise ValueError("Savant returned another pitcher or season; existing values preserved.")
    return records


def refresh_approach_angles(
    *, source_path=None, pitcher_id=None, season=None, workers=4, progress=None
):
    conditions = [
        or_(Pitch.approach_angle_version.is_(None), Pitch.approach_angle_version < ANGLE_VERSION),
        Pitch.pitch_type.notin_(("", "UN")),
        func.coalesce(func.lower(Pitch.description), "").notin_(
            ("automatic_ball", "automatic_strike")
        ),
    ]
    if pitcher_id is not None:
        conditions.append(Pitch.pitcher_id == pitcher_id)
    if season is not None:
        conditions.append(Game.season == season)
    query = (
        select(Pitch.pitch_id, Pitch.pitcher_id, Game.season, Game.game_date)
        .join(Game, Game.game_pk == Pitch.game_pk)
        .where(*conditions)
    )
    pending = {
        row.pitch_id: (row.pitcher_id, row.season, row.game_date)
        for row in db.session.execute(query)
    }
    summary = {
        "pitcher_seasons": len({(pid, year) for pid, year, _ in pending.values()}),
        "updated_pitches": 0,
        "vaa_pitches": 0,
        "haa_pitches": 0,
        "failed": [],
    }
    if progress:
        progress(f"Backfilling approach angles for {len(pending):,} existing pitches.")

    def apply(records, ids):
        updates = []
        for key in ids:
            owner, year, record = records[key]
            if (owner, year) != pending[key][:2]:
                raise ValueError("Source pitch ownership differs from the existing database.")
            updates.append(
                {"pitch_id": key, **record, "haaaa_model_id": None, "vaa_adj_model_id": None}
            )
        for start in range(0, len(updates), 2000):
            db.session.execute(update(Pitch), updates[start : start + 2000])
        return updates

    def account(updates):
        summary["updated_pitches"] += len(updates)
        summary["vaa_pitches"] += sum(row["vaa"] is not None for row in updates)
        summary["haa_pitches"] += sum(row["haa"] is not None for row in updates)
        for row in updates:
            del pending[row["pitch_id"]]

    # Read only trajectory fields from an existing CSV first. This avoids
    # network downloads for the bundled public cohort and accepts local caches.
    if source_path is not None and pending:
        source = Path(source_path)
        if not source.is_file():
            raise ValueError(f"Trajectory CSV does not exist: {source}")
        updates = []
        seen = set()
        try:
            for chunk in pd.read_csv(source, usecols=lambda c: c in SOURCE_FIELDS, chunksize=5000):
                records = _source_records(chunk)
                if seen.intersection(records):
                    raise ValueError("Source CSV has duplicate pitch identities across chunks.")
                seen.update(records)
                updates.extend(apply(records, pending.keys() & records.keys()))
            db.session.commit()
        except Exception:
            db.session.rollback()
            raise
        account(updates)
        if progress:
            progress(f"CSV cache: updated {len(updates):,} existing pitches.")

    jobs = {}
    for key, (pid, year, day) in pending.items():
        job = jobs.setdefault((pid, year), {"first": day, "last": day, "ids": []})
        job["first"], job["last"] = min(day, job["first"]), max(day, job["last"])
        job["ids"].append(key)

    def acquire(item):
        (pid, year), job = item
        try:
            records = fetch_trajectory_values((pid, year, job["first"], job["last"]))
            if set(job["ids"]) - records.keys():
                raise ValueError("Existing pitches absent from source; pitcher-season preserved.")
            return pid, year, job["ids"], records, None
        except Exception as error:
            return pid, year, job["ids"], None, str(error)

    def results():
        # Bound downloaded results as well as simultaneous requests on full local databases.
        items = iter(jobs.items())
        with ThreadPoolExecutor(max_workers=workers) as executor:
            active = {executor.submit(acquire, item) for _, item in zip(range(workers), items)}
            while active:
                done, active = wait(active, return_when=FIRST_COMPLETED)
                for future in done:
                    yield future.result()
                    item = next(items, None)
                    if item is not None:
                        active.add(executor.submit(acquire, item))

    for pid, year, ids, records, error in results():
        if error:
            summary["failed"].append({"pitcher_id": pid, "season": year, "error": error})
            if progress:
                progress(f"Preserved {pid} ({year}): {error}")
            continue
        try:
            updates = apply(records, ids)
            db.session.commit()
        except Exception:
            db.session.rollback()
            raise
        account(updates)
        if progress:
            progress(f"Backfilled {pid} ({year}): {len(updates):,} existing pitches.")
    return summary
