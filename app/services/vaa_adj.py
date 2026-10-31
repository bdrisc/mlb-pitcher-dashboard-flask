"""Frozen, location-adjusted vertical approach angle in signed degrees."""

from __future__ import annotations

import hashlib
import json
from functools import lru_cache
from math import isfinite, sqrt
from pathlib import Path

from sqlalchemy import func, or_, select, update

from app.extensions import db
from app.models import Game, Pitch

MODEL_PATH = Path(__file__).resolve().parents[2] / "data/vaa_adj_reference_2025.json"
VAA_ADJ_FIELDS = ("expected_vaa", "vaa_adj", "vaa_adj_model_id")


def _finite(*values):
    try:
        return all(value is not None and isfinite(float(value)) for value in values)
    except (TypeError, ValueError):
        return False


@lru_cache(maxsize=1)
def load_reference():
    if not MODEL_PATH.is_file():
        return None
    reference = json.loads(MODEL_PATH.read_text())
    core = {key: value for key, value in reference.items() if key != "model_id"}
    digest = hashlib.sha256(json.dumps(core, sort_keys=True, allow_nan=False).encode()).hexdigest()
    if digest != reference["model_id"]:
        raise ValueError("Frozen VAAAdj reference integrity check failed.")
    if (
        reference["target"] != "front_plane_vaa_degrees"
        or reference["features"] != ["intercept", "plate_z_front"]
        or reference["train_season"] >= reference["applies_from_season"]
    ):
        raise ValueError("VAAAdj reference target or temporal scope is invalid.")
    return reference


def front_plate_z(*, season, plate_z, vz0=None, vy0=None, az=None, ay=None):
    """Convert the 2026+ midpoint location to the front plane of the raw VAA."""
    if not _finite(season, plate_z):
        return None
    if int(season) < 2026:
        return float(plate_z)
    if not _finite(vz0, vy0, az, ay) or float(vy0) >= 0:
        return None
    vz0, vy0, az, ay = map(float, (vz0, vy0, az, ay))

    def time_at(y):
        distance = 50.0 - y
        discriminant = vy0 * vy0 - 2 * ay * distance
        if not isfinite(discriminant) or discriminant <= 0:
            return None
        return 2 * distance / (-vy0 + sqrt(discriminant))

    front, middle = time_at(17 / 12), time_at(17 / 24)
    if front is None or middle is None:
        return None
    z = float(plate_z) + vz0 * (front - middle) + 0.5 * az * (front**2 - middle**2)
    return z if isfinite(z) else None


def score_vaa_adj(
    *, season, pitch_type, plate_z, vaa, vz0=None, vy0=None, az=None, ay=None, reference=None
):
    reference = reference if reference is not None else load_reference()
    result = {
        "expected_vaa": None,
        "vaa_adj": None,
        "vaa_adj_model_id": reference["model_id"] if reference else None,
    }
    if not reference or not _finite(season, vaa):
        return result
    if int(season) < reference["applies_from_season"]:
        return result
    group = reference["groups"].get(pitch_type)
    if not group:
        return result
    location = front_plate_z(season=season, plate_z=plate_z, vz0=vz0, vy0=vy0, az=az, ay=ay)
    if location is None:
        return result
    intercept, location_beta = group["coefficients"]
    expected = intercept + location_beta * location
    if _finite(expected):
        result["expected_vaa"] = float(expected)
        result["vaa_adj"] = float(vaa) - expected
    return result


def backfill_vaa_adj(*, season=None, pitcher_id=None, batch_size=2000, progress=None):
    reference = load_reference()
    if reference is None:
        raise ValueError("Frozen VAAAdj reference artifact is missing.")
    conditions = [
        or_(Pitch.vaa_adj_model_id.is_(None), Pitch.vaa_adj_model_id != reference["model_id"]),
        Game.season >= reference["applies_from_season"],
        Pitch.pitch_type.notin_(("", "UN")),
        func.coalesce(func.lower(Pitch.description), "").notin_(
            ("automatic_ball", "automatic_strike")
        ),
    ]
    if season is not None:
        conditions.append(Game.season == season)
    if pitcher_id is not None:
        conditions.append(Pitch.pitcher_id == pitcher_id)
    count = db.session.scalar(select(func.count()).select_from(Pitch).join(Game).where(*conditions))
    result = {
        "model_id": reference["model_id"],
        "processed_pitches": 0,
        "scored_pitches": 0,
        "unavailable_pitches": 0,
    }
    if progress:
        progress(f"Scoring VAAAdj for {count:,} existing pitches using the frozen 2025 reference.")
    last_id = ""
    while True:
        rows = (
            db.session.execute(
                select(
                    Pitch.pitch_id,
                    Game.season,
                    Pitch.pitch_type,
                    Pitch.plate_z,
                    Pitch.vaa,
                    Pitch.vz0,
                    Pitch.vy0,
                    Pitch.az,
                    Pitch.ay,
                )
                .join(Game, Game.game_pk == Pitch.game_pk)
                .where(*conditions, Pitch.pitch_id > last_id)
                .order_by(Pitch.pitch_id)
                .limit(batch_size)
            )
            .mappings()
            .all()
        )
        if not rows:
            break
        updates = []
        for row in rows:
            values = dict(row)
            key = values.pop("pitch_id")
            updates.append({"pitch_id": key, **score_vaa_adj(**values, reference=reference)})
        try:
            db.session.execute(update(Pitch), updates)
            db.session.commit()
        except Exception:
            db.session.rollback()
            raise
        scored = sum(row["vaa_adj"] is not None for row in updates)
        result["processed_pitches"] += len(updates)
        result["scored_pitches"] += scored
        result["unavailable_pitches"] += len(updates) - scored
        last_id = rows[-1]["pitch_id"]
        if progress:
            progress(
                f"VAAAdj: {result['processed_pitches']:,}/{count:,} processed; "
                f"{result['scored_pitches']:,} scored."
            )
    return result
