"""Import the exact weighted outcomes used by Baseball Savant's Statcast Search."""

from __future__ import annotations

import json
from collections import defaultdict
from concurrent.futures import ThreadPoolExecutor
from decimal import Decimal
from math import isfinite

from sqlalchemy import or_, select, update

from app.extensions import db
from app.models import Game, Pitch
from app.services.run_value_refresh import _download

# Savant's search excludes these interrupted at-bats from its PA results.
NON_PA_EVENTS = ("truncated_pa",)


def fetch_woba_outcomes(job):
    pitcher, season, first, last = job
    params = {
        "player_type": "pitcher",
        "pitchers_lookup[]": pitcher,
        "hfSea": f"{season}|",
        "hfGT": "R|PO|S|A|",
        "game_date_gt": first.isoformat(),
        "game_date_lt": last.isoformat(),
        "min_pitches": 0,
        "min_results": 0,
        "hfFlag": "is_pa|",
        "outputFormat": "json",
        "chk_stats_woba": "on",
    }
    rows = json.loads(_download("/statcast_search", {**params, "group_by": "name-event"}))
    aggregate = json.loads(_download("/statcast_search", {**params, "group_by": "name"}))
    return verify_woba_outcomes(rows, aggregate, pitcher, season)


def verify_woba_outcomes(rows, aggregate, pitcher, season):
    if rows == [] and aggregate == []:
        return {}
    if not isinstance(rows, list) or not isinstance(aggregate, list) or len(aggregate) != 1:
        raise ValueError("Savant did not return pitch details and a pitcher aggregate.")

    outcomes = {}
    total = Decimal(0)
    denominator = 0
    for row in rows:
        if row["pitcher"] != pitcher or row["game_year"] != season or row["is_pa"] != 1:
            raise ValueError("Savant returned an outcome outside the pitcher-season PA sample.")
        identity = (row["game_pk"], row["at_bat_number"], row["pitch_number"])
        if any(type(value) is not int for value in identity) or not row["events"]:
            raise ValueError("Savant returned a PA without a pitch identity or outcome.")
        key = "_".join(map(str, identity))
        if key in outcomes:
            raise ValueError("Savant returned duplicate pitch identities.")
        numerator = row["fangraphs_woba_numer"]
        denom = row["fangraphs_woba_denom"]
        if (
            not isinstance(numerator, (int, float))
            or not isfinite(numerator)
            or numerator < 0
            or denom not in (0, 1)
            or (not denom and numerator != 0)
        ):
            raise ValueError("Savant returned invalid wOBA components.")
        total += Decimal(str(numerator))
        denominator += denom
        outcomes[key] = (row["events"], numerator, denom)

    official = aggregate[0]
    if len(outcomes) != official["pa"] or abs(float(total) - official["woba_value"]) > 1e-7:
        raise ValueError("PA counts or weights differ from Savant's wOBA aggregate.")
    if denominator and abs(float(total / denominator) - official["woba"]) > 0.00050001:
        raise ValueError("Exact weights and denominator do not reproduce Savant's wOBA.")
    return outcomes


def refresh_woba(*, season=None, pitcher_id=None, workers=4, progress=None):
    conditions = [
        Pitch.events.is_not(None),
        Pitch.events != "",
        Pitch.events.notin_(NON_PA_EVENTS),
        or_(Pitch.savant_woba_numerator.is_(None), Pitch.savant_woba_denominator.is_(None)),
    ]
    if season is not None:
        conditions.append(Game.season == season)
    if pitcher_id is not None:
        conditions.append(Pitch.pitcher_id == pitcher_id)
    jobs = defaultdict(list)
    for row in db.session.execute(
        select(Pitch.pitch_id, Pitch.pitcher_id, Pitch.events, Game.season, Game.game_date)
        .join(Game, Game.game_pk == Pitch.game_pk)
        .where(*conditions)
    ):
        jobs[row.pitcher_id, row.season].append((row.pitch_id, row.events, row.game_date))
    summary = {
        "pitcher_seasons": len(jobs),
        "pending_outcomes": sum(map(len, jobs.values())),
        "updated_outcomes": 0,
        "failed": [],
    }
    if progress:
        progress(f"Fetching exact Savant wOBA outcomes for {len(jobs):,} pitcher-seasons.")

    def acquire(item):
        (pid, year), stored = item
        try:
            days = [day for _, _, day in stored]
            outcomes = fetch_woba_outcomes((pid, year, min(days), max(days)))
            updates = []
            for key, event, _ in stored:
                if key in outcomes and event == outcomes[key][0]:
                    _, numerator, denom = outcomes[key]
                    updates.append(
                        {
                            "pitch_id": key,
                            "savant_woba_numerator": numerator,
                            "savant_woba_denominator": denom,
                        }
                    )
            missing = len(stored) - len(updates)
            error = f"{missing:,} stored outcomes did not match Savant." if missing else None
            return pid, year, updates, error
        except Exception as exc:
            return pid, year, [], str(exc)

    with ThreadPoolExecutor(max_workers=workers) as executor:
        for pid, year, updates, error in executor.map(acquire, jobs.items()):
            try:
                if updates:
                    db.session.execute(update(Pitch), updates)
                    db.session.commit()
                    summary["updated_outcomes"] += len(updates)
            except Exception as exc:
                db.session.rollback()
                error = str(exc)
            if error:
                summary["failed"].append({"pitcher_id": pid, "season": year, "error": error})
            if progress:
                line = f"wOBA {pid} ({year}): {len(updates):,} verified outcomes."
                progress(f"{line} {error}" if error else line)
    return summary
