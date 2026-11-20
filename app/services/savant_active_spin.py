"""Store official, spin-based Baseball Savant active-spin percentages.

The public Statcast pitch CSV has total spin and 2D axis, but lacks the 3D
release spin vector necessary to calculate measured spin efficiency. Therefore
these values are separate full-season *published* references and do not
follow date, count, or batter-hand filters.
"""

from __future__ import annotations

import math
from datetime import datetime, timezone

import pandas as pd
from sqlalchemy import select

from app.extensions import db
from app.models import SavantActiveSpin

# Official Savant Active Spin leaderboard fields, not an inferred movement proxy.
SAVANT_SPIN_FIELDS = {
    "active_spin_fourseam": "FF",
    "active_spin_sinker": "SI",
    "active_spin_cutter": "FC",
    "active_spin_changeup": "CH",
    "active_spin_splitter": "FS",
    "active_spin_curve": "CU",
    "active_spin_slider": "SL",
    "active_spin_sweeper": "ST",
    "active_spin_slurve": "SV",
}


def import_savant_active_spin(frame: pd.DataFrame, season: int) -> dict:
    """Validate all rows before committing official spin-based percentages."""
    required = {"entity_id", *SAVANT_SPIN_FIELDS}
    if frame.empty or not required.issubset(frame.columns):
        raise ValueError(
            "Not an official Savant active-spin CSV with pitcher IDs and pitch fields."
        )
    if "year" in frame.columns:
        permitted = {str(season), f"{season}_spin-based"}
        if not frame["year"].astype(str).isin(permitted).all():
            raise ValueError("Spin-efficiency source does not match the selected season/method.")

    ids = pd.to_numeric(frame["entity_id"], errors="coerce")
    if ids.isna().any() or (ids <= 0).any() or not (ids == ids.astype("int64")).all():
        raise ValueError("Active-spin source contains invalid MLB pitcher IDs.")
    if ids.duplicated().any():
        raise ValueError("Active-spin source contains duplicate MLB pitcher IDs.")

    values: dict[tuple[int, str], float] = {}
    for i, record in frame.iterrows():
        player_id = int(ids.loc[i])
        for field, code in SAVANT_SPIN_FIELDS.items():
            raw = record[field]
            if pd.isna(raw) or str(raw).strip() in ("", "—", "-"):
                continue
            try:
                value = float(str(raw).replace("%", "").strip())
            except (TypeError, ValueError) as exc:
                raise ValueError(f"Invalid {field} for MLB ID {player_id}: {raw!r}") from exc
            if not math.isfinite(value) or not 0 <= value <= 100:
                raise ValueError(f"Invalid {field} percent for MLB ID {player_id}: {raw!r}")
            values[(player_id, code)] = value

    if not values:
        raise ValueError("No measured active-spin percentages found in Savant response.")

    now = datetime.now(timezone.utc)
    existing = {
        (row.mlb_id, row.pitch_type): row
        for row in db.session.scalars(
            select(SavantActiveSpin).where(SavantActiveSpin.season == season)
        )
    }
    for (mlb_id, pitch_type), value in values.items():
        record = existing.get((mlb_id, pitch_type))
        if record is None:
            record = SavantActiveSpin(mlb_id=mlb_id, season=season, pitch_type=pitch_type)
            db.session.add(record)
        record.active_spin_pct = value
        record.updated_at = now
    db.session.commit()
    return {"provider": "baseball_savant_spin_based", "season": season, "pitch_rows": len(values)}


def published_active_spin(pitcher_id: int, season: int | None) -> dict[str, float]:
    """Return exact full-season published percentages, or no values if no season."""
    if season is None:
        return {}
    return {
        record.pitch_type: record.active_spin_pct
        for record in db.session.scalars(
            select(SavantActiveSpin).where(
                SavantActiveSpin.mlb_id == pitcher_id,
                SavantActiveSpin.season == season,
            )
        )
    }
