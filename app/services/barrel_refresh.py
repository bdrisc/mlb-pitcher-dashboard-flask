"""Backfill official barrel classifications on existing pitches, without re-ingestion."""

from __future__ import annotations

import io
from concurrent.futures import FIRST_COMPLETED, ThreadPoolExecutor, wait
from pathlib import Path

import pandas as pd
from sqlalchemy import func, select, update

from app.extensions import db
from app.models import Game, Pitch
from app.services.run_value_refresh import _download

IDENTITY = ("game_pk", "at_bat_number", "pitch_number")
FIELDS = (*IDENTITY, "pitcher", "game_year", "description", "launch_speed_angle")
BBE_DESCRIPTIONS = ("hit_into_play", "hit_into_play_no_out", "hit_into_play_score")


def source_records(frame):
    if missing := set(FIELDS) - set(frame.columns):
        raise ValueError("Barrel source is missing columns: " + ", ".join(sorted(missing)))
    for key in (*IDENTITY, "pitcher", "game_year", "launch_speed_angle"):
        values = pd.to_numeric(frame[key], errors="raise")
        if (values.dropna() % 1 != 0).any():
            raise ValueError("Barrel source identities and classifications must be integers.")
        if key != "launch_speed_angle" and values.isna().any():
            raise ValueError("Barrel source identities must not be missing.")
        frame[key] = values
    if frame[list(IDENTITY)].duplicated().any():
        raise ValueError("Barrel source has duplicate pitch identities.")
    if not frame.launch_speed_angle.dropna().between(1, 6).all():
        raise ValueError("Barrel classifications must be between 1 and 6.")
    records = {}
    for row in frame.to_dict(orient="records"):
        if str(row["description"]).lower() not in BBE_DESCRIPTIONS:
            continue
        key = "_".join(str(int(row[f])) for f in IDENTITY)
        value = row["launch_speed_angle"]
        records[key] = (
            int(row["pitcher"]),
            int(row["game_year"]),
            None if pd.isna(value) else int(value),
        )
    return records


def fetch_barrel_values(job):
    pid, year, first, last = job
    payload = _download(
        "/statcast_search/csv",
        {
            "player_type": "pitcher",
            "pitchers_lookup[]": pid,
            "hfSea": f"{year}|",
            "hfGT": "R|PO|S|A|",
            "game_date_gt": first.isoformat(),
            "game_date_lt": last.isoformat(),
            "min_pitches": 0,
            "min_results": 0,
            "type": "details",
            "all": "true",
        },
    )
    frame = pd.read_csv(io.BytesIO(payload), usecols=lambda c: c in FIELDS)
    if len(frame) >= 30000:
        raise ValueError("Barrel response may be truncated; saved values preserved.")
    records = source_records(frame)
    if any(owner != pid or season != year for owner, season, _ in records.values()):
        raise ValueError("Barrel source returned another pitcher or season.")
    return records


def refresh_barrels(*, source_paths=(), season=None, pitcher_id=None, workers=4, progress=None):
    conditions = [
        func.lower(Pitch.description).in_(BBE_DESCRIPTIONS),
        Pitch.barrel_checked.is_not(True),
    ]
    if season is not None:
        conditions.append(Game.season == season)
    if pitcher_id is not None:
        conditions.append(Pitch.pitcher_id == pitcher_id)
    pending = {
        row.pitch_id: (row.pitcher_id, row.season, row.game_date)
        for row in db.session.execute(
            select(Pitch.pitch_id, Pitch.pitcher_id, Game.season, Game.game_date)
            .join(Game, Game.game_pk == Pitch.game_pk)
            .where(*conditions)
        )
    }
    result = {"pending_bbe": len(pending), "updated_bbe": 0, "failed": []}
    if progress:
        progress(f"Backfilling official barrel data for {len(pending):,} existing batted balls.")

    def apply(records, ids):
        updates = []
        for key in ids:
            owner, year, value = records[key]
            if (owner, year) != pending[key][:2]:
                raise ValueError("Barrel source ownership differs from the stored pitch.")
            updates.append({"pitch_id": key, "launch_speed_angle": value, "barrel_checked": True})
        for start in range(0, len(updates), 2000):
            db.session.execute(update(Pitch), updates[start : start + 2000])
        return [row["pitch_id"] for row in updates]

    def account(ids):
        result["updated_bbe"] += len(ids)
        for key in ids:
            pending.pop(key)

    for path in source_paths:
        if not pending:
            break
        source = Path(path)
        paths = (
            sorted([*source.rglob("*.csv"), *source.rglob("*.csv.gz")])
            if source.is_dir()
            else [source]
        )
        if not source.exists():
            raise ValueError(f"Barrel CSV path does not exist: {source}")
        for file in paths:
            if not pending:
                break
            updated, seen = [], set()
            try:
                for frame in pd.read_csv(file, usecols=lambda c: c in FIELDS, chunksize=5000):
                    # Older caches without this column cannot provide classifications.
                    if "launch_speed_angle" not in frame:
                        break
                    records = source_records(frame)
                    if seen.intersection(records):
                        raise ValueError("Barrel CSV has duplicate identities across chunks.")
                    seen.update(records)
                    updated.extend(apply(records, pending.keys() & records.keys()))
                db.session.commit()
            except Exception:
                db.session.rollback()
                raise
            account(updated)
            if progress and updated:
                progress(f"CSV cache: backfilled {len(updated):,} existing batted balls.")

    jobs = {}
    for key, (pid, year, day) in pending.items():
        job = jobs.setdefault((pid, year), {"first": day, "last": day, "ids": []})
        job["first"], job["last"] = min(day, job["first"]), max(day, job["last"])
        job["ids"].append(key)

    def acquire(item):
        (pid, year), job = item
        try:
            records = fetch_barrel_values((pid, year, job["first"], job["last"]))
            if set(job["ids"]) - records.keys():
                raise ValueError(
                    "Stored batted balls absent from source; pitcher-season preserved."
                )
            return pid, year, job["ids"], records, None
        except Exception as error:
            return pid, year, job["ids"], None, str(error)

    def results():
        items = iter(jobs.items())
        with ThreadPoolExecutor(max_workers=workers) as pool:
            active = {pool.submit(acquire, item) for _, item in zip(range(workers), items)}
            while active:
                done, active = wait(active, return_when=FIRST_COMPLETED)
                for future in done:
                    yield future.result()
                    if (item := next(items, None)) is not None:
                        active.add(pool.submit(acquire, item))

    for pid, year, ids, records, error in results():
        if not error:
            try:
                updated = apply(records, ids)
                db.session.commit()
                account(updated)
            except Exception as exc:
                db.session.rollback()
                error = str(exc)
        if error:
            result["failed"].append({"pitcher_id": pid, "season": year, "error": error})
            if progress:
                progress(f"Preserved {pid} ({year}): {error}")
        elif progress:
            progress(f"Backfilled {pid} ({year}): {len(ids):,} existing batted balls.")
    result["remaining_bbe"] = len(pending)
    return result
