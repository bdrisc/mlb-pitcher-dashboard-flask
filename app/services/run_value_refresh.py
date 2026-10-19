"""Refresh only existing pitch run values from Savant, verified against its neutral aggregate."""

from __future__ import annotations

import io
import json
from concurrent.futures import ThreadPoolExecutor
from urllib.error import URLError
from urllib.parse import urlencode
from urllib.request import Request, urlopen

import pandas as pd
from sqlalchemy import func, select, update

from app.extensions import db
from app.models import Game, Pitch


class RunValueRefreshError(ValueError):
    """The source could not be verified; preserve the saved pitcher values."""


def _download(path, params):
    request = Request(
        "https://baseballsavant.mlb.com" + path + "?" + urlencode(params),
        headers={"User-Agent": "Mozilla/5.0", "Accept": "application/json,text/csv"},
    )
    for attempt in range(2):
        try:
            with urlopen(request, timeout=30) as response:
                return response.read()
        except (URLError, TimeoutError):
            if attempt:
                raise


def validate_source(frame, aggregate):
    required = {"game_pk", "at_bat_number", "pitch_number", "delta_run_exp"}
    if not required.issubset(frame.columns):
        raise RunValueRefreshError("Savant did not return the required pitch CSV columns.")
    if len(frame) >= 30000:
        raise RunValueRefreshError("Savant response may be truncated; saved values preserved.")
    values = pd.to_numeric(frame["delta_run_exp"], errors="raise")
    if len(aggregate) != 1 or "delev_pitcher_run_exp" not in aggregate[0]:
        raise RunValueRefreshError("Savant did not return its explicit context-neutral total.")
    official = aggregate[0]
    count = int(values.notna().sum())
    total = -float(values.sum())
    if count != int(official["pitches"]):
        raise RunValueRefreshError("Pitch counts differ from the Savant neutral aggregate.")
    if abs(total - float(official["delev_pitcher_run_exp"])) > 0.005:
        raise RunValueRefreshError("CSV values do not reproduce the Savant neutral total.")
    identities = frame[["game_pk", "at_bat_number", "pitch_number"]]
    if identities.isna().any().any() or identities.duplicated().any():
        raise RunValueRefreshError("Savant pitch identities are missing or duplicated.")
    return {
        f"{int(row.game_pk)}_{int(row.at_bat_number)}_{int(row.pitch_number)}": (
            None if pd.isna(value) else float(value)
        )
        for row, value in zip(identities.itertuples(index=False), values, strict=True)
    }


def fetch_verified_values(job):
    pitcher_id, season, first, last = job
    params = {
        "player_type": "pitcher",
        "pitchers_lookup[]": pitcher_id,
        "hfSea": f"{season}|",
        "hfGT": "R|PO|S|A|",
        "game_date_gt": first.isoformat(),
        "game_date_lt": last.isoformat(),
        "min_pitches": 0,
        "min_results": 0,
    }
    csv = _download("/statcast_search/csv", {**params, "type": "details", "all": "true"})
    frame = pd.read_csv(
        io.BytesIO(csv),
        usecols=lambda c: c in {"game_pk", "at_bat_number", "pitch_number", "delta_run_exp"},
    )
    official = json.loads(
        _download(
            "/statcast_search",
            {
                **params,
                "group_by": "name",
                "outputFormat": "json",
                "chk_stats_delev_pitcher_run_exp": "on",
                "chk_stats_delev_pitcher_run_value_per_100": "on",
            },
        )
    )
    return validate_source(frame, official)


def refresh_run_values(*, pitcher_id=None, season=None, workers=4, progress=None):
    query = select(
        Pitch.pitcher_id, Game.season, func.min(Game.game_date), func.max(Game.game_date)
    ).join(Game, Game.game_pk == Pitch.game_pk)
    if pitcher_id is not None:
        query = query.where(Pitch.pitcher_id == pitcher_id)
    if season is not None:
        query = query.where(Game.season == season)
    jobs = db.session.execute(query.group_by(Pitch.pitcher_id, Game.season)).all()
    summary = {"pitcher_seasons": len(jobs), "updated_pitches": 0, "refreshed": 0, "failed": []}

    def acquire(job):
        try:
            return job, fetch_verified_values(job), None
        except Exception as error:
            return job, None, str(error)

    if progress:
        progress(f"Refreshing run values for {len(jobs)} stored pitcher-seasons.")
    with ThreadPoolExecutor(max_workers=workers) as executor:
        for job, values, error in executor.map(acquire, jobs):
            pid, year, *_ = job
            if error:
                summary["failed"].append({"pitcher_id": pid, "season": year, "error": error})
                continue
            ids = db.session.scalars(
                select(Pitch.pitch_id)
                .join(Game, Game.game_pk == Pitch.game_pk)
                .where(Pitch.pitcher_id == pid, Game.season == year)
            ).all()
            missing = set(ids) - values.keys()
            if missing:
                summary["failed"].append(
                    {
                        "pitcher_id": pid,
                        "season": year,
                        "error": f"{len(missing)} existing pitches absent from source; preserved.",
                    }
                )
                continue
            updates = [{"pitch_id": key, "delta_run_expectancy": values[key]} for key in ids]
            try:
                if updates:
                    db.session.execute(update(Pitch), updates)
                db.session.commit()
                summary["updated_pitches"] += len(updates)
                summary["refreshed"] += 1
                if progress:
                    progress(f"Verified {pid} ({year}): updated {len(updates)} existing pitches.")
            except Exception:
                db.session.rollback()
                raise
    return summary
