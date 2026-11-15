"""Full-MLB arm-slot movement reference for Pitch Shape "vs. AVG" metrics.

The public dashboard contains only a selected pitcher cohort. It must never
construct a purported MLB-wide baseline from that cohort. Both deployments
read the same compact, independently exported full-league Statcast reference.
"""

from __future__ import annotations

import csv
import gzip
from collections import defaultdict
from functools import lru_cache
from math import isfinite
from pathlib import Path

from sqlalchemy import func, select

from app.extensions import db
from app.models import Game, Pitch, Player

REFERENCE_DIR = Path(__file__).resolve().parents[2] / "data"
REFERENCE_FIELDS = (
    "pitcher_id",
    "pitch_type",
    "hand",
    "arm_angle_bin",
    "pitch_count",
    "hb_sum",
    "ivb_sum",
)
MIN_MLB_PITCHERS = 300
MIN_MLB_PITCHES = 200_000
MIN_COMPARISON_PITCHERS = 5
MIN_COMPARISON_PITCHES = 100
ARM_ANGLE_WINDOW_DEGREES = 5.0


def reference_path(season: int) -> Path:
    return REFERENCE_DIR / f"league_movement_{season}.csv.gz"


@lru_cache(maxsize=8)
def _load_reference(path_str: str, modified_ns: int):
    groups = defaultdict(list)
    with gzip.open(path_str, "rt", encoding="utf-8", newline="") as stream:
        reader = csv.DictReader(stream)
        if not set(REFERENCE_FIELDS).issubset(reader.fieldnames or []):
            raise ValueError("League movement reference CSV has missing required fields.")
        for row in reader:
            side = row["hand"]
            code = row["pitch_type"]
            angle_bin = int(row["arm_angle_bin"])
            pitcher_id = int(row["pitcher_id"])
            count = int(row["pitch_count"])
            hb_sum = float(row["hb_sum"])
            ivb_sum = float(row["ivb_sum"])
            if side not in ("R", "L") or not code or not -90 <= angle_bin <= 90:
                raise ValueError("Invalid league movement category or arm-angle bin.")
            if count <= 0 or not isfinite(hb_sum) or not isfinite(ivb_sum):
                raise ValueError("Invalid league movement sums or sample counts.")
            groups[(side, code)].append((angle_bin, pitcher_id, count, hb_sum, ivb_sum))
    return groups


def movement_vs_average(
    *,
    season: int | None,
    pitch_type: str,
    throwing_hand: str | None,
    arm_angle: float | None,
    horizontal_break: float | None,
    vertical_break: float | None,
) -> dict:
    """Return signed inch differences vs same-hand, same-type, ±5° MLB averages."""
    result = {
        "hb_vs_avg": None,
        "ivb_vs_avg": None,
        "movement_avg_pitches": 0,
        "movement_avg_pitchers": 0,
        "movement_avg_arm_angle": None,
    }
    if (
        season is None
        or throwing_hand not in ("R", "L")
        or arm_angle is None
        or horizontal_break is None
        or vertical_break is None
        or not all(isfinite(float(x)) for x in (arm_angle, horizontal_break, vertical_break))
    ):
        return result
    path = reference_path(season)
    if not path.is_file():
        return result
    rows = _load_reference(str(path), path.stat().st_mtime_ns).get((throwing_hand, pitch_type), ())
    eligible = [
        row for row in rows if abs(row[0] + 0.5 - float(arm_angle)) <= ARM_ANGLE_WINDOW_DEGREES
    ]
    count = sum(row[2] for row in eligible)
    pitchers = len({row[1] for row in eligible})
    result["movement_avg_pitches"] = count
    result["movement_avg_pitchers"] = pitchers
    result["movement_avg_arm_angle"] = round(float(arm_angle), 1)
    if count < MIN_COMPARISON_PITCHES or pitchers < MIN_COMPARISON_PITCHERS:
        return result

    league_hb = sum(row[3] for row in eligible) / count
    league_ivb = sum(row[4] for row in eligible) / count
    hand_sign = -1 if throwing_hand == "R" else 1
    result["hb_vs_avg"] = round((float(horizontal_break) - league_hb) * hand_sign, 1)
    result["ivb_vs_avg"] = round(float(vertical_break) - league_ivb, 1)
    return result


def export_full_league_reference(season: int, destination: Path | None = None) -> dict:
    """Export entire MLB-season pitch-type movement by 1° bin and pitcher.

    Reject subset databases, including the deployed 50-pitcher public database.
    This is read-only on the source database and writes just the compressed CSV.
    """
    destination = destination or reference_path(season)
    angle_bin = func.floor(Pitch.arm_angle)
    stmt = (
        select(
            Pitch.pitcher_id,
            Pitch.pitch_type,
            Player.throws.label("hand"),
            angle_bin.label("angle_bin"),
            func.count(Pitch.pitch_id).label("pitch_count"),
            func.sum(Pitch.horizontal_break_inches).label("hb_sum"),
            func.sum(Pitch.vertical_break_inches).label("ivb_sum"),
        )
        .select_from(Pitch)
        .join(Game, Game.game_pk == Pitch.game_pk)
        .join(Player, Player.mlb_id == Pitch.pitcher_id)
        .where(
            Game.season == season,
            Game.game_type == "R",
            Player.throws.in_(("L", "R")),
            Pitch.pitch_type.notin_(("", "UN")),
            Pitch.arm_angle.between(-90, 90),
            Pitch.horizontal_break_inches.is_not(None),
            Pitch.vertical_break_inches.is_not(None),
            func.coalesce(func.lower(Pitch.description), "").notin_(
                ("automatic_ball", "automatic_strike")
            ),
        )
        .group_by(Pitch.pitcher_id, Pitch.pitch_type, Player.throws, angle_bin)
        .order_by(Pitch.pitcher_id, Pitch.pitch_type, angle_bin)
    )
    rows = db.session.execute(stmt).mappings().all()
    pitchers = len({row["pitcher_id"] for row in rows})
    pitches = sum(int(row["pitch_count"]) for row in rows)
    if pitchers < MIN_MLB_PITCHERS or pitches < MIN_MLB_PITCHES:
        raise ValueError(
            f"Not a full MLB season: {pitchers} pitchers, {pitches} eligible pitches. "
            f"At least {MIN_MLB_PITCHERS} pitchers and {MIN_MLB_PITCHES} pitches are "
            "required. Do not use the 50-pitcher public database."
        )

    destination.parent.mkdir(parents=True, exist_ok=True)
    temporary = destination.with_name(destination.name + ".tmp")
    try:
        with gzip.open(temporary, "wt", encoding="utf-8", newline="") as stream:
            writer = csv.DictWriter(stream, fieldnames=REFERENCE_FIELDS)
            writer.writeheader()
            for row in rows:
                writer.writerow(
                    {
                        "pitcher_id": row["pitcher_id"],
                        "pitch_type": row["pitch_type"],
                        "hand": row["hand"],
                        "arm_angle_bin": int(row["angle_bin"]),
                        "pitch_count": int(row["pitch_count"]),
                        "hb_sum": f"{float(row['hb_sum']):.8f}",
                        "ivb_sum": f"{float(row['ivb_sum']):.8f}",
                    }
                )
        temporary.replace(destination)
    finally:
        temporary.unlink(missing_ok=True)
    return {
        "season": season,
        "pitchers": pitchers,
        "pitches": pitches,
        "rows": len(rows),
        "path": str(destination),
    }
