"""Geometric tunneling of genuine consecutive pitches, independent of outcomes."""

from __future__ import annotations

from math import hypot, isfinite, sqrt

from sqlalchemy import and_, select
from sqlalchemy.orm import aliased

from app.extensions import db
from app.models import Game, Pitch
from app.services.database_queries import pitch_filter_conditions
from app.services.pitch_data import PITCH_NAME_MAP

FRONT_Y = 17 / 12
MIDDLE_Y = 17 / 24
TUNNEL_DISTANCE_FT = 23.8
TUNNEL_Y = FRONT_Y + TUNNEL_DISTANCE_FT
GEOMETRY_FIELDS = ("plate_x", "plate_z", "vx0", "vy0", "vz0", "ax", "ay", "az")
RELEASE_FIELDS = ("release_pos_x", "release_pos_y", "release_pos_z")
METRICS = (
    "release_gap_inches",
    "tunnel_gap_inches",
    "plate_gap_inches",
    "flight_time_gap_ms",
    "late_separation_inches",
)


def _finite(*values):
    try:
        return all(v is not None and isfinite(float(v)) for v in values)
    except (ValueError, TypeError, OverflowError):
        return False


def time_at_y(vy0, ay, y):
    """Signed time from Statcast's y=50-ft reference; release may precede it."""
    if not _finite(vy0, ay, y) or vy0 >= 0:
        return None
    distance = 50.0 - y
    discriminant = vy0 * vy0 - 2 * ay * distance
    if not isfinite(discriminant) or discriminant <= 0:
        return None
    t = 2 * distance / (-vy0 + sqrt(discriminant))
    return t if isfinite(t) else None


def pitch_geometry(row):
    """Anchor x/z at the documented plate plane, not at the measured release."""
    if not _finite(row.get("season"), *(row.get(k) for k in GEOMETRY_FIELDS)):
        return None
    v = {k: float(row[k]) for k in GEOMETRY_FIELDS}
    anchor_y = MIDDLE_Y if int(row["season"]) >= 2026 else FRONT_Y
    anchor, tunnel, front = (time_at_y(v["vy0"], v["ay"], y) for y in (anchor_y, TUNNEL_Y, FRONT_Y))
    if any(t is None for t in (anchor, tunnel, front)) or not 0 < tunnel < front:
        return None

    def position(t):
        dt, dt2 = t - anchor, t * t - anchor * anchor
        x = v["plate_x"] + v["vx0"] * dt + 0.5 * v["ax"] * dt2
        z = v["plate_z"] + v["vz0"] * dt + 0.5 * v["az"] * dt2
        return (x, z) if _finite(x, z) else None

    tunnel_point, plate_point = position(tunnel), position(front)
    if tunnel_point is None or plate_point is None:
        return None
    release = None
    if (
        _finite(*(row.get(k) for k in RELEASE_FIELDS))
        and TUNNEL_Y < float(row["release_pos_y"]) <= 65
    ):
        release = tuple(float(row[k]) for k in RELEASE_FIELDS)
    flight = None
    release_y = row.get("release_pos_y")
    if _finite(release_y) and TUNNEL_Y < float(release_y) <= 65:
        release_time = time_at_y(v["vy0"], v["ay"], float(release_y))
        if release_time is not None and release_time < tunnel:
            flight = front - release_time
    return {"tunnel": tunnel_point, "plate": plate_point, "release": release, "flight": flight}


def pair_metrics(a, b):
    if a is None or b is None:
        return None

    def distance(left, right):
        if left is None or right is None:
            return None
        value = 12 * hypot(*(x - y for x, y in zip(left, right, strict=True)))
        return value if isfinite(value) else None

    flight = None
    if a["flight"] is not None and b["flight"] is not None:
        flight = 1000 * abs(a["flight"] - b["flight"])
    tunnel_gap, plate_gap = distance(a["tunnel"], b["tunnel"]), distance(a["plate"], b["plate"])
    if tunnel_gap is None or plate_gap is None:
        return None
    return {
        "release_gap_inches": distance(a["release"], b["release"]),
        "tunnel_gap_inches": tunnel_gap,
        "plate_gap_inches": plate_gap,
        "late_separation_inches": plate_gap - tunnel_gap,
        "flight_time_gap_ms": flight if _finite(flight) else None,
    }


class _Summary:
    def __init__(self):
        self.observed = 0
        self.scored = 0
        self.sums = dict.fromkeys(METRICS, 0.0)
        self.counts = dict.fromkeys(METRICS, 0)

    def add(self, values):
        self.observed += 1
        if values is None:
            return
        self.scored += 1
        for key in METRICS:
            value = values[key]
            if _finite(value):
                self.sums[key] += value
                self.counts[key] += 1

    def payload(self):
        return {
            "observed_pair_count": self.observed,
            "pair_count": self.scored,
            "missing_geometry_pairs": self.observed - self.scored,
            **{
                key: self.sums[key] / self.counts[key] if self.counts[key] else None
                for key in METRICS
            },
            "metric_pair_counts": self.counts.copy(),
        }


def build_pitch_tunneling(pitcher_id, filters):
    """Filter the second pitch while joining its real, unfiltered predecessor.

    The existing natural-key constraint and sequence index make this exact
    self-join efficient and prevent missing rows from creating false neighbors.
    """
    previous = aliased(Pitch, name="previous_pitch")
    fields = ("pitch_id", "pitch_type", "description", *GEOMETRY_FIELDS, *RELEASE_FIELDS)
    statement = (
        select(
            Game.season,
            *(getattr(Pitch, key).label(key) for key in fields),
            *(getattr(previous, key).label(f"previous_{key}") for key in fields),
        )
        .select_from(Pitch)
        .join(Game, Game.game_pk == Pitch.game_pk)
        .join(
            previous,
            and_(
                previous.game_pk == Pitch.game_pk,
                previous.pitcher_id == Pitch.pitcher_id,
                previous.batter_id == Pitch.batter_id,
                previous.at_bat_number == Pitch.at_bat_number,
                previous.pitch_number == Pitch.pitch_number - 1,
            ),
        )
        .where(*pitch_filter_conditions(filters, pitcher_id=pitcher_id))
        .order_by(Pitch.game_pk, Pitch.at_bat_number, Pitch.pitch_number)
    )
    overall, sequences, pitch_types, geometry = _Summary(), {}, {}, {}
    for row in db.session.execute(statement).mappings():
        a = {key: row[f"previous_{key}"] for key in fields}
        b = {key: row[key] for key in fields}
        if any(
            p["pitch_type"] in (None, "", "UN")
            or (p["description"] or "").lower() in ("automatic_ball", "automatic_strike")
            for p in (a, b)
        ):
            continue
        for p in (a, b):
            if p["pitch_id"] not in geometry:
                geometry[p["pitch_id"]] = pitch_geometry({**p, "season": row["season"]})
        values = pair_metrics(geometry[a["pitch_id"]], geometry[b["pitch_id"]])
        key = (a["pitch_type"], b["pitch_type"])
        sequences.setdefault(key, _Summary()).add(values)
        pitch_types.setdefault(b["pitch_type"], _Summary()).add(values)
        overall.add(values)
    pairs = [
        {"pitch_a": a, "pitch_b": b, **summary.payload()} for (a, b), summary in sequences.items()
    ]
    by_pitch = [
        {"pitch_type": code, "pitch_name": PITCH_NAME_MAP.get(code, code), **summary.payload()}
        for code, summary in pitch_types.items()
    ]
    return {
        "method": "geometric_fixed_plane_v1",
        "tunnel_distance_from_front_ft": TUNNEL_DISTANCE_FT,
        "tunnel_y_ft": TUNNEL_Y,
        "filter_pitch": "second",
        "includes_same_type_pairs": True,
        "overall": overall.payload(),
        "pairs": sorted(pairs, key=lambda p: (-p["pair_count"], p["pitch_a"], p["pitch_b"])),
        "by_pitch_type": sorted(by_pitch, key=lambda p: (-p["pair_count"], p["pitch_type"])),
    }


def add_tunneling_to_separation(separation, tunneling):
    """Pool both sequence directions using each measurement's own coverage."""
    grouped = {}
    for sequence in tunneling["pairs"]:
        key = tuple(sorted((sequence["pitch_a"], sequence["pitch_b"])))
        grouped.setdefault(key, []).append(sequence)
    for pair in separation["pairs"]:
        sequences = grouped.get(tuple(sorted((pair["pitch_a"], pair["pitch_b"]))), [])
        pair["observed_sequence_pair_count"] = sum(s["observed_pair_count"] for s in sequences)
        for metric, count_key in (
            ("release_gap_inches", "release_pair_count"),
            ("late_separation_inches", "late_separation_pair_count"),
        ):
            samples = [(s[metric], s["metric_pair_counts"][metric]) for s in sequences]
            samples = [(value, count) for value, count in samples if count and _finite(value)]
            count = sum(n for _, n in samples)
            pair[count_key] = count
            pair[metric] = sum(value * n for value, n in samples) / count if count else None
    return separation
