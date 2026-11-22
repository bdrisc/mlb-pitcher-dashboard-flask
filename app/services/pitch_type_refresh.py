"""Safely reconcile existing pitcher pitch types with current Baseball Savant IDs.

Unlike re-ingestion, this never touches movement, velocity, tracked angles,
run values, expected outcomes, or records outside the stored pitcher pool.
Every pitch ID must match the official source before any change is committed.
"""

from __future__ import annotations

import io
from concurrent.futures import ThreadPoolExecutor

import pandas as pd
from sqlalchemy import func, select, update

from app.extensions import db
from app.models import Game, Pitch
from app.services.pitch_data import PITCH_NAME_MAP
from app.services.run_value_refresh import _download


class PitchTypeSourceError(ValueError):
    """The source is incomplete or differs from the stored pitch identities."""


def validate_pitch_type_source(frame: pd.DataFrame, pitcher_id: int):
    fields = ("game_pk", "at_bat_number", "pitch_number", "pitcher", "pitch_type")
    if not set(fields).issubset(frame.columns) or frame.empty or len(frame) >= 30000:
        raise PitchTypeSourceError("Savant pitch classification CSV is missing or incomplete.")
    identities = frame[list(fields[:-1])]
    if identities.isna().any().any() or identities.duplicated().any():
        raise PitchTypeSourceError("Savant pitch identities are missing or duplicated.")
    if not (pd.to_numeric(frame["pitcher"], errors="coerce") == pitcher_id).all():
        raise PitchTypeSourceError("Savant returned another pitcher's records.")
    result = {}
    for game, at_bat, number, pitcher, raw_code in frame[list(fields)].itertuples(
        index=False, name=None
    ):
        key = f"{int(game)}_{int(at_bat)}_{int(number)}"
        if pd.isna(raw_code) or not str(raw_code).strip():
            result[key] = None
            continue
        code = str(raw_code).strip().upper()
        if len(code) > 4 or not code.isalnum():
            raise PitchTypeSourceError(f"Unexpected official pitch code: {raw_code!r}")
        result[key] = code
    return result


def fetch_pitch_type_source(job):
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
        "type": "details",
        "all": "true",
    }
    csv_bytes = _download("/statcast_search/csv", params)
    frame = pd.read_csv(
        io.BytesIO(csv_bytes),
        usecols=lambda column: (
            column
            in {
                "game_pk",
                "at_bat_number",
                "pitch_number",
                "pitcher",
                "pitch_type",
            }
        ),
    )
    return validate_pitch_type_source(frame, pitcher_id)


def _is_bulk_knuckle_curve_relabel(by_id, edits):
    """Allow a narrow, verified historical CU-to-KC source-vintage correction.

    Gavin Williams' older 2026 source labeled almost every knuckle curve as CU.
    Savant now uses KC. This is different from an arbitrary change to 20%+
    of a pitcher's classifications, so keep strict bounds on all other edits.
    """
    if not edits or len(edits) > int(len(by_id) * 0.30):
        return False
    curve_relabels = sum(
        by_id[item["pitch_id"]] == "CU" and item["pitch_type"] == "KC" for item in edits
    )
    return (
        curve_relabels >= 100
        and curve_relabels * 100 >= 98 * len(edits)
        and len(edits) - curve_relabels <= 2
    )



def _is_verified_walker_sweeper_relabel(by_id, edits, *, pitcher_id, season, extras):
    """Permit only the fully identity-verified 2026 Ryan Walker SL->ST source correction.

    The 2026 full-season audit established 609 stored pitches: 397 SI, 187 SL,
    25 FF; all 187 sliders are now classified ST by Savant. Its export includes
    10 additional source-only pitch IDs. Reject any other state instead of
    loosening the normal 10% bulk-change safety limit.
    """
    if (pitcher_id, season) != (676254, 2026):
        return False
    if len(by_id) != 609 or len(extras) != 10 or len(edits) != 187:
        return False
    counts = {
        code: sum(current == code for current in by_id.values())
        for code in ("SI", "SL", "FF")
    }
    if counts != {"SI": 397, "SL": 187, "FF": 25}:
        return False
    return all(
        by_id[item["pitch_id"]] == "SL" and item["pitch_type"] == "ST"
        for item in edits
    )


def plan_pitch_type_changes(
    existing, official, *, max_change_fraction=0.10, pitcher_id=None, season=None
):
    """Return updates only for changed codes, never missing source classifications."""
    by_id = dict(existing)
    if len(by_id) != len(existing):
        raise PitchTypeSourceError("Stored pitch IDs are duplicated.")
    missing = set(by_id) - set(official)
    extras = set(official) - set(by_id)
    # Savant can include additional source rows that were never ingested.
    # They are not local pitches and must never be inserted or updated here.
    # Every stored ID must still exist in Savant, and extras must be small.
    max_extras = max(3, int(len(by_id) * 0.02))
    if missing or len(extras) > max_extras:
        raise PitchTypeSourceError(
            "Official pitch IDs do not match the stored season safely "
            f"(missing={len(missing)}, extra={len(extras)}, max_extra={max_extras})."
        )
    edits = []
    for pitch_id, current in by_id.items():
        code = official[pitch_id]
        if code and code != current:
            edits.append(
                {
                    "pitch_id": pitch_id,
                    "pitch_type": code,
                    "pitch_name": PITCH_NAME_MAP.get(code, code),
                }
            )
    if len(edits) > max(1, int(len(by_id) * max_change_fraction)):
        approved_source_shift = _is_bulk_knuckle_curve_relabel(
            by_id, edits
        ) or _is_verified_walker_sweeper_relabel(
            by_id, edits, pitcher_id=pitcher_id, season=season, extras=extras
        )
        if not approved_source_shift:
            raise PitchTypeSourceError(
                f"{len(edits)} reclassifications exceed the safety cap; saved data preserved."
            )
    return edits


def refresh_pitch_types(
    *, pitcher_id=None, season=2026, audit_ids=None, apply=False, workers=4, progress=None
):
    """Check official pitch IDs and optionally update only pitch_type/pitch_name."""
    query = (
        select(Pitch.pitcher_id, Game.season, func.min(Game.game_date), func.max(Game.game_date))
        .join(Game, Game.game_pk == Pitch.game_pk)
        .where(Game.season == season)
    )
    if pitcher_id is not None:
        query = query.where(Pitch.pitcher_id == pitcher_id)
    if audit_ids is not None:
        if not audit_ids:
            raise ValueError("The supplied audit contains no eligible pitcher IDs.")
        query = query.where(Pitch.pitcher_id.in_(audit_ids))
    jobs = db.session.execute(query.group_by(Pitch.pitcher_id, Game.season)).all()
    summary = {
        "pitcher_seasons": len(jobs),
        "verified": 0,
        "changed_pitches": 0,
        "knuckle_curve_relabels": 0,
        "ignored_extra_source_pitches": 0,
        "applied": apply,
        "failed": [],
    }

    def acquire(job):
        try:
            return job, fetch_pitch_type_source(job), None
        except Exception as error:
            return job, None, str(error)

    if progress:
        progress(f"Checking official pitch types for {len(jobs)} stored pitcher-seasons.")
    with ThreadPoolExecutor(max_workers=workers) as executor:
        for job, official, error in executor.map(acquire, jobs):
            pid, year, *_ = job
            if error:
                summary["failed"].append({"pitcher_id": pid, "season": year, "error": error})
                continue
            existing = db.session.execute(
                select(Pitch.pitch_id, Pitch.pitch_type)
                .join(Game, Game.game_pk == Pitch.game_pk)
                .where(Pitch.pitcher_id == pid, Game.season == year)
            ).all()
            try:
                edits = plan_pitch_type_changes(existing, official, pitcher_id=pid, season=year)
                if apply and edits:
                    db.session.execute(update(Pitch), edits)
                    db.session.commit()
                summary["verified"] += 1
                summary["changed_pitches"] += len(edits)
                by_id = dict(existing)
                curve_relabels = sum(
                    by_id[item["pitch_id"]] == "CU" and item["pitch_type"] == "KC" for item in edits
                )
                summary["knuckle_curve_relabels"] += curve_relabels
                extra = len(set(official) - set(by_id))
                summary["ignored_extra_source_pitches"] += extra
                if progress:
                    action = "updated" if apply else "would update"
                    progress(
                        f"{pid} ({year}): {action} {len(edits)} pitch classifications "
                        f"({curve_relabels} CU->KC); ignored {extra} source-only IDs."
                    )
            except Exception as error:
                db.session.rollback()
                summary["failed"].append({"pitcher_id": pid, "season": year, "error": str(error)})
    return summary
