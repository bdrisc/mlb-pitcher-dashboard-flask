"""Export season-wide, unweighted pitcher/pitch-type role distributions.

Run only against the audited complete regular-season local MLB database.
Never run against the public cohort. Read-only SQL; atomic reference write.
"""

from __future__ import annotations

import argparse
import json
from collections import defaultdict

from sqlalchemy import func, select

from app.extensions import db
from app.models import Game, Pitch, Player
from app.services.pitch_roles import (
    MIN_PEERS,
    ROLE_FIELDS,
    VERSION,
    count_key,
    count_masks,
    peer_key,
    reference_path,
    role_values,
)
from app.services.pitcher_profiles import _metric_columns


def export(season, destination=None, future_constants=None):
    physical = func.coalesce(func.lower(Pitch.description), "").notin_(
        ("automatic_ball", "automatic_strike")
    )
    base = (Game.season == season, Game.game_type == "R")
    totals = db.session.execute(
        select(
            func.count(func.distinct(Pitch.pitcher_id)),
            func.count(Pitch.pitch_id),
            func.count(func.distinct(Game.game_pk)),
            func.max(Game.game_date),
        )
        .select_from(Pitch)
        .join(Game, Game.game_pk == Pitch.game_pk)
        .where(*base, physical)
    ).one()
    pitchers, physical_pitches, games, through = totals
    minimum = (300, 200000, 600) if season >= 2027 else (750, 650000, 2400)
    if pitchers < minimum[0] or physical_pitches < minimum[1] or games < minimum[2]:
        raise ValueError(
            f"Incomplete MLB season: {pitchers} pitchers, {physical_pitches} pitches, {games} games"
        )
    duplicate = db.session.execute(
        select(Pitch.game_pk, Pitch.at_bat_number, Pitch.pitch_number)
        .join(Game, Game.game_pk == Pitch.game_pk)
        .where(*base)
        .group_by(Pitch.game_pk, Pitch.at_bat_number, Pitch.pitch_number)
        .having(func.count() > 1)
        .limit(1)
    ).first()
    if duplicate:
        raise ValueError("Duplicate natural pitch key; reference not written")
    metrics = [c for c in _metric_columns(future_constants) if c.key in ROLE_FIELDS]
    if {c.key for c in metrics} != set(ROLE_FIELDS):
        raise ValueError("Shared metric definition missing")
    dimensions = (
        Pitch.pitcher_id,
        Pitch.pitch_type,
        Player.throws,
        Pitch.batter_side,
        Pitch.balls,
        Pitch.strikes,
    )
    stmt = (
        select(*dimensions, *metrics)
        .select_from(Pitch)
        .join(Game, Game.game_pk == Pitch.game_pk)
        .join(Player, Player.mlb_id == Pitch.pitcher_id)
        .where(*base, Player.throws.in_(("L", "R")), Pitch.pitch_type.notin_(("", "UN")))
        .group_by(*dimensions)
    )
    masks = count_masks()
    mask_by_count = {
        (b, s): [count_key(m) for m in masks if (b, s) in m] for b in range(4) for s in range(3)
    }
    # Pool raw numerators/denominators, never average rates across counts or sides.
    grouped = defaultdict(dict)
    for row in db.session.execute(stmt).mappings():
        for side in ("ALL", row["batter_side"]) if row["batter_side"] in ("L", "R") else ("ALL",):
            for scope in mask_by_count[(row["balls"], row["strikes"])]:
                target = grouped[(row["pitcher_id"], row["pitch_type"], row["throws"], side, scope)]
                for field in ROLE_FIELDS:
                    v = row[field]
                    if v is not None:
                        target[field] = target.get(field, 0) + v
    distributions = defaultdict(list)
    for (_, code, hand, side, scope), vals in grouped.items():
        vals = {k: vals.get(k) for k in ROLE_FIELDS}
        for metric, cell in role_values(vals).items():
            if cell["qualified"]:
                distributions[peer_key(code, hand, side, scope, metric)].append(cell["value"])
    payload = {
        "version": VERSION,
        "season": season,
        "pitchers": pitchers,
        "physical_pitches": physical_pitches,
        "games": games,
        "through": through.isoformat(),
        "distributions": {k: sorted(v) for k, v in sorted(distributions.items()) if v},
    }
    if not any(len(v) >= MIN_PEERS for v in payload["distributions"].values()):
        raise ValueError("No qualifying peer groups")
    if season >= 2027 and destination is None:
        raise ValueError("Future role exports require an explicit isolated output path.")
    path = destination or reference_path(season)
    if season >= 2027 and path.exists():
        raise ValueError("Future reference already exists.")
    tmp = path.with_suffix(".tmp")
    try:
        tmp.write_text(
            json.dumps(payload, separators=(",", ":"), allow_nan=False) + "\n", encoding="utf-8"
        )
        tmp.replace(path)
    finally:
        tmp.unlink(missing_ok=True)
    return {
        "path": str(path),
        "pitchers": pitchers,
        "physical_pitches": physical_pitches,
        "games": games,
        "through": through.isoformat(),
        "distributions": len(payload["distributions"]),
    }


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--season", required=True, type=int)
    args = parser.parse_args()
    from wsgi import app

    with app.app_context():
        print(json.dumps(export(args.season), indent=2))


if __name__ == "__main__":
    main()
