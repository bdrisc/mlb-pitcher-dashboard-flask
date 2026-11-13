"""Store only values directly published by FanGraphs and Baseball Savant.

These season references never change the Statcast pitch/player tables and are
not reconstructed from pitch outcomes. MLBAM IDs are required for all joins.
"""

from __future__ import annotations

import math
from datetime import datetime, timezone

import pandas as pd
from sqlalchemy import select

from app.extensions import db
from app.models import FanGraphsStuff, PublishedPitchingMetric

SPLITS = ("ALL", "L", "R")
FANGRAPHS_URL = "https://www.fangraphs.com/leaders/major-league"
SAVANT_URL = "https://baseballsavant.mlb.com/leaderboard/expected_statistics"


def _float(value):
    if value is None or pd.isna(value) or str(value).strip() in ("", "-", "—"):
        return None
    try:
        result = float(str(value).replace(",", ""))
    except ValueError as exc:
        raise ValueError(f"Invalid published pitching value: {value!r}.") from exc
    if not math.isfinite(result) or not -100 <= result <= 100:
        raise ValueError(f"Invalid published pitching value: {value!r}.")
    return result


def _integer(value):
    if value is None or pd.isna(value) or str(value).strip() == "":
        return None
    try:
        number = int(float(value))
    except (ValueError, TypeError) as exc:
        raise ValueError(f"Invalid published pitcher ID: {value!r}.") from exc
    return number if number > 0 else None


def _reference_rows(pitcher_id, season):
    if season is None:
        return {}
    return {
        row.batter_side: row
        for row in db.session.scalars(
            select(PublishedPitchingMetric).where(
                PublishedPitchingMetric.mlb_id == pitcher_id,
                PublishedPitchingMetric.season == season,
            )
        )
    }


def _display_reference(row, season, side):
    fg_values = ("fip", "xfip", "siera")
    return {
        **{metric: None if row is None else getattr(row, metric) for metric in fg_values},
        "xera": row.xera if row is not None and side == "ALL" else None,
        "reference_season": season,
        "reference_batter_side": side,
        "reference_scope": "full_season" if side == "ALL" else "batter_handedness",
        "reference_fangraphs_updated": (
            row.fangraphs_updated_at.isoformat()
            if row is not None and row.fangraphs_updated_at is not None
            else None
        ),
        "reference_savant_updated": (
            row.savant_updated_at.isoformat()
            if row is not None and side == "ALL" and row.savant_updated_at is not None
            else None
        ),
    }


def published_references(pitcher_id, season):
    """Return source-backed ALL/L/R records, with NULL for unavailable splits."""
    rows = _reference_rows(pitcher_id, season)
    return {
        side: _display_reference(rows.get(side), season, side)
        for side in SPLITS
    }


def _column(frame, choices):
    for option in choices:
        if option in frame.columns:
            return option
    return None


def _validate_season(frame, season, candidates):
    column = _column(frame, candidates)
    if column is not None:
        observed = pd.to_numeric(frame[column], errors="coerce")
        if observed.isna().any() or not observed.eq(season).all():
            raise ValueError("Published stats contain a different season.")


def _fg_id_map(season):
    return {
        grade.fangraphs_id: grade.mlb_id
        for grade in db.session.scalars(
            select(FanGraphsStuff).where(
                FanGraphsStuff.season == season, FanGraphsStuff.category == "ALL"
            )
        )
    }


def _apply_rows(values, season, side, provider):
    if not values:
        raise ValueError(f"No valid {provider} pitcher-season results; saved stats preserved.")
    ids = [row[0] for row in values]
    if len(set(ids)) != len(ids):
        raise ValueError("Duplicate MLB IDs in source response; saved stats preserved.")
    existing = {
        row.mlb_id: row
        for row in db.session.scalars(
            select(PublishedPitchingMetric).where(
                PublishedPitchingMetric.season == season,
                PublishedPitchingMetric.batter_side == side,
                PublishedPitchingMetric.mlb_id.in_(ids),
            )
        )
    }
    now = datetime.now(timezone.utc)
    for mlb_id, fg_id, metrics in values:
        row = existing.get(mlb_id)
        if row is None:
            row = PublishedPitchingMetric(mlb_id=mlb_id, season=season, batter_side=side)
            db.session.add(row)
        for name, value in metrics.items():
            # A source can withhold individual values. Never replace a verified
            # published value with a newly missing/blank value.
            if value is not None:
                setattr(row, name, value)
        if provider == "fangraphs":
            row.fangraphs_id = fg_id
            row.fangraphs_updated_at = now
        else:
            row.savant_updated_at = now
    db.session.commit()
    return {"provider": provider, "season": season, "split": side, "rows": len(values)}


def import_fangraphs_published(frame, season, side="ALL"):
    """Import official FanGraphs FIP, xFIP, SIERA, optionally versus R/L hitters."""
    if side not in SPLITS:
        raise ValueError("FanGraphs split must be ALL, L, or R.")
    frame = frame.copy()
    frame.columns = frame.columns.astype(str).str.strip()
    for field in ("FIP", "xFIP", "SIERA"):
        if field not in frame.columns:
            raise ValueError(f"FanGraphs source is missing {field}; saved stats preserved.")
    _validate_season(frame, season, ("Season", "season"))
    mlb_column = _column(frame, ("mlb_id", "xMLBAMID", "MLBAMID"))
    fg_column = _column(frame, ("IDfg", "playerid", "PlayerId"))
    if mlb_column is None and fg_column is None:
        raise ValueError("FanGraphs source has no MLBAM or FanGraphs ID.")
    mapping = _fg_id_map(season) if mlb_column is None else {}
    records = []
    for row in frame.to_dict("records"):
        fg_id = _integer(row.get(fg_column)) if fg_column else None
        mlb_id = _integer(row.get(mlb_column)) if mlb_column else None
        if mlb_id is None and fg_id is not None:
            mlb_id = mapping.get(str(fg_id))
        if mlb_id is None:
            continue
        metrics = {"fip": _float(row["FIP"]), "xfip": _float(row["xFIP"]),
                   "siera": _float(row["SIERA"])}
        if any(value is not None for value in metrics.values()):
            records.append((mlb_id, str(fg_id) if fg_id is not None else None, metrics))
    return _apply_rows(records, season, side, "fangraphs")


def import_savant_xera(frame, season):
    """Import exact published Savant pitcher xERA (full season only)."""
    frame = frame.copy()
    frame.columns = frame.columns.astype(str).str.strip()
    id_column = _column(frame, ("player_id", "mlb_id"))
    if id_column is None or "xera" not in frame.columns:
        raise ValueError("Savant source requires player_id and xera columns.")
    _validate_season(frame, season, ("year", "Year"))
    records = []
    for row in frame.to_dict("records"):
        mlb_id = _integer(row.get(id_column))
        if mlb_id is None:
            continue
        xera = _float(row["xera"])
        if xera is not None:
            records.append((mlb_id, None, {"xera": xera}))
    return _apply_rows(records, season, "ALL", "savant")
