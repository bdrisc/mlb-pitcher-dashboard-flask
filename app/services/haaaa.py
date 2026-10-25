"""Frozen, prior-season expectations for signed horizontal approach angle."""

from __future__ import annotations

import hashlib
import json
from functools import lru_cache
from math import isfinite, sqrt
from pathlib import Path

from sqlalchemy import func, or_, select, update

from app.extensions import db
from app.models import Game, Pitch, Player

MODEL_PATH = Path(__file__).resolve().parents[2] / "data/haaaa_reference_2025.json"
HAAAA_FIELDS = ("expected_haa", "haaaa", "haaaa_model_id", "pitcher_throws")


@lru_cache(maxsize=1)
def load_reference():
    # The same checked-in artifact is used locally and publicly; no UI refitting.
    if not MODEL_PATH.is_file():
        return None
    reference = json.loads(MODEL_PATH.read_text())
    core = {key: value for key, value in reference.items() if key != "model_id"}
    digest = hashlib.sha256(json.dumps(core, sort_keys=True, allow_nan=False).encode()).hexdigest()
    if digest != reference["model_id"]:
        raise ValueError("Frozen HAAAA reference integrity check failed.")
    if (
        reference["target"] != "front_plane_haa_degrees"
        or reference["train_season"] >= reference["applies_from_season"]
    ):
        raise ValueError("HAAAA reference target or temporal scope is invalid.")
    return reference


def _finite(*values):
    try:
        return all(value is not None and isfinite(float(value)) for value in values)
    except (TypeError, ValueError):
        return False


def front_plate_x(*, season, plate_x, vx0=None, vy0=None, ax=None, ay=None):
    """Anchor Statcast's plate location to the front plane, including the 2026 ABS change."""
    if not _finite(season, plate_x):
        return None
    if int(season) < 2026:
        return float(plate_x)
    if not _finite(vx0, vy0, ax, ay) or float(vy0) >= 0:
        return None
    vx0, vy0, ax, ay = map(float, (vx0, vy0, ax, ay))

    def time_at(y):
        d = 50.0 - y
        discriminant = vy0 * vy0 - 2 * ay * d
        if not isfinite(discriminant) or discriminant <= 0:
            return None
        return 2 * d / (-vy0 + sqrt(discriminant))

    front, middle = time_at(17 / 12), time_at(17 / 24)
    if front is None or middle is None:
        return None
    value = float(plate_x) + vx0 * (front - middle) + 0.5 * ax * (front * front - middle * middle)
    return value if isfinite(value) else None


def score_haaaa(
    *,
    season,
    pitch_type,
    throws,
    release_pos_x,
    plate_x,
    haa,
    vx0=None,
    vy0=None,
    ax=None,
    ay=None,
    reference=None,
):
    reference = reference if reference is not None else load_reference()
    result = {
        "expected_haa": None,
        "haaaa": None,
        "haaaa_model_id": reference["model_id"] if reference else None,
    }
    if not reference or not _finite(season, release_pos_x, haa):
        return result
    if int(season) < reference["applies_from_season"]:
        return result
    group = reference["groups"].get(f"{pitch_type}:{throws}")
    if not group:
        return result
    location = front_plate_x(season=season, plate_x=plate_x, vx0=vx0, vy0=vy0, ax=ax, ay=ay)
    if location is None:
        return result
    intercept, release_beta, location_beta = group["coefficients"]
    expected = intercept + release_beta * float(release_pos_x) + location_beta * location
    if _finite(expected):
        result["expected_haa"] = float(expected)
        result["haaaa"] = float(haa) - expected
    return result


def backfill_haaaa(*, season=None, pitcher_id=None, batch_size=2000, progress=None):
    reference = load_reference()
    if reference is None:
        raise ValueError("Frozen HAAAA reference artifact is missing.")
    conditions = [
        or_(Pitch.haaaa_model_id.is_(None), Pitch.haaaa_model_id != reference["model_id"]),
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
        progress(
            f"Scoring HAAAA for {count:,} existing pitches using the frozen 2025 MLB reference."
        )
    validation_path = MODEL_PATH.with_name("haaaa_validation_2026.json")
    switches = set()
    if validation_path.is_file():
        switches = set(json.loads(validation_path.read_text()).get("switch_pitcher_ids", []))
    last_id = ""
    while True:
        rows = (
            db.session.execute(
                select(
                    Pitch.pitch_id,
                    Game.season,
                    Pitch.pitch_type,
                    Player.throws.label("player_throws"),
                    Pitch.pitcher_throws,
                    Pitch.pitcher_id,
                    Pitch.release_pos_x,
                    Pitch.plate_x,
                    Pitch.haa,
                    Pitch.vx0,
                    Pitch.vy0,
                    Pitch.ax,
                    Pitch.ay,
                )
                .join(Game, Game.game_pk == Pitch.game_pk)
                .join(Player, Player.mlb_id == Pitch.pitcher_id)
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
            owner = values.pop("pitcher_id")
            per_pitch_hand = values.pop("pitcher_throws")
            player_hand = values.pop("player_throws")
            values["throws"] = per_pitch_hand or (None if owner in switches else player_hand)
            updates.append({"pitch_id": key, **score_haaaa(**values, reference=reference)})
        try:
            db.session.execute(update(Pitch), updates)
            db.session.commit()
        except Exception:
            db.session.rollback()
            raise
        scored = sum(row["haaaa"] is not None for row in updates)
        result["processed_pitches"] += len(updates)
        result["scored_pitches"] += scored
        result["unavailable_pitches"] += len(updates) - scored
        last_id = rows[-1]["pitch_id"]
        if progress:
            progress(
                f"HAAAA: {result['processed_pitches']:,}/{count:,} processed; "
                f"{result['scored_pitches']:,} scored."
            )
    return result
