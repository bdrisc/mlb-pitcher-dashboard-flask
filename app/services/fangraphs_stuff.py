"""Import published FanGraphs grades without recomputing their model."""

import math
from datetime import datetime, timezone

import pandas as pd
from sqlalchemy import delete, select

from app.extensions import db
from app.models import FanGraphsStuff

CATEGORIES = ("FA", "SI", "FC", "SL", "ST", "CU", "KC", "CH", "FS", "FO")
PITCH_CATEGORIES = {"FF": "FA", "FA": "FA", **{p: p for p in CATEGORIES if p != "FA"}}


def import_grades(frame, season, crosswalk=None):
    frame = frame.copy()
    frame.columns = frame.columns.str.strip()
    if "Stuff+" not in frame.columns:
        raise ValueError("The file must include the FanGraphs Stuff+ column.")
    if "Season" in frame and not frame["Season"].eq(season).all():
        raise ValueError("The file contains seasons other than the requested season.")
    id_column = next((c for c in ("IDfg", "PlayerId", "playerid") if c in frame), None)
    if id_column is None:
        raise ValueError("Missing FanGraphs player ID (IDfg, PlayerId, or playerid).")
    mapping = {}
    if crosswalk is not None:
        valid = crosswalk.dropna(subset=["key_fangraphs", "key_mlbam"])
        mapping = {str(int(float(r.key_fangraphs))): int(r.key_mlbam) for r in valid.itertuples()}
    pending = []
    seen = set()
    skipped = 0
    for row in frame.to_dict("records"):
        fg_id = str(int(float(row[id_column])))
        raw_mlb = row.get("mlb_id", row.get("MLBAMID"))
        mlb_id = int(raw_mlb) if pd.notna(raw_mlb) and raw_mlb is not None else mapping.get(fg_id)
        if mlb_id is None:
            skipped += 1
            continue
        if mlb_id in seen:
            raise ValueError(
                "Duplicate pitcher rows; export combined season totals, not team splits."
            )
        seen.add(mlb_id)
        for category in ("ALL", *CATEGORIES):
            values = []
            for overall, prefix in (
                ("Stuff+", "Stf+"),
                ("Location+", "Loc+"),
                ("Pitching+", "Pit+"),
            ):
                raw = row.get(overall if category == "ALL" else f"{prefix} {category}")
                value = None
                if raw is not None and not pd.isna(raw) and str(raw).strip() not in ("", "-", "—"):
                    parsed = float(raw)
                    if math.isfinite(parsed):
                        value = parsed
                values.append(value)
            if any(value is not None for value in values):
                pending.append((mlb_id, fg_id, category, *values))
    if not pending:
        raise ValueError("No usable grades matched MLB IDs; existing data were preserved.")
    now = datetime.now(timezone.utc)
    try:
        db.session.execute(
            delete(FanGraphsStuff).where(
                FanGraphsStuff.season == season, FanGraphsStuff.mlb_id.in_(seen)
            )
        )
        for mlb_id, fg_id, category, value, location, pitching in pending:
            grade = FanGraphsStuff(mlb_id=mlb_id, season=season, category=category)
            db.session.add(grade)
            grade.fangraphs_id = fg_id
            grade.stuff_plus = value
            grade.location_plus = location
            grade.pitching_plus = pitching
            grade.updated_at = now
        db.session.commit()
    except Exception:
        db.session.rollback()
        raise
    return {"grades": len(pending), "pitchers": len(seen), "unmatched_pitchers": skipped}


def profile_grades(pitcher_id, season):
    if season is None:
        return {
            "season": None,
            "overall": None,
            "pitches": {},
            "location_plus": None,
            "pitching_plus": None,
            "pitch_location": {},
            "pitch_pitching": {},
            "updated_at": None,
            "message": "Select one season to view FanGraphs Stuff+.",
        }
    rows = db.session.scalars(
        select(FanGraphsStuff).where(
            FanGraphsStuff.mlb_id == pitcher_id, FanGraphsStuff.season == season
        )
    ).all()
    grades = {r.category: r.stuff_plus for r in rows}
    return {
        "season": season,
        "overall": grades.get("ALL"),
        "location_plus": next((r.location_plus for r in rows if r.category == "ALL"), None),
        "pitching_plus": next((r.pitching_plus for r in rows if r.category == "ALL"), None),
        "pitch_location": {
            p: next((r.location_plus for r in rows if r.category == c), None)
            for p, c in PITCH_CATEGORIES.items()
        },
        "pitch_pitching": {
            p: next((r.pitching_plus for r in rows if r.category == c), None)
            for p, c in PITCH_CATEGORIES.items()
        },
        "pitches": {p: grades.get(c) for p, c in PITCH_CATEGORIES.items()},
        "updated_at": max(r.updated_at for r in rows).isoformat() if rows else None,
        "message": (
            "Full-season reference; date, team, count and handedness filters "
            "do not change these grades."
        )
        if rows
        else "FanGraphs Stuff+ has not been imported for this pitcher and season.",
    }
