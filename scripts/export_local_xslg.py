"""Export local expected SLG values for the public pitcher pool without modifying data.

Examples:
    python -m scripts.export_local_xslg --pitcher 605400 --season 2026
    python -m scripts.export_local_xslg --all --season 2026

Creates one small compressed CSV in outputs/ (ignored by Git). The export
includes pitch ID, pitcher ID, game date, event and *existing* expected SLG.
It excludes all credentials, unpublished tables, and unrelated local pitchers.
"""

from __future__ import annotations

import argparse
import csv
import gzip
import json
from pathlib import Path
from urllib.request import Request, urlopen

from dotenv import load_dotenv

PUBLIC_URL = "https://mlb-pitch-intelligence.onrender.com"


def public_pitcher_ids(season, public_url=PUBLIC_URL):
    """Fetch only the selected public MLB IDs; never fetch local private players."""
    url = f"{public_url.rstrip('/')}/api/v1/pitchers?season={season}"
    request = Request(url, headers={"User-Agent": "MLB-Pitcher-Parity-Export/1.0"})
    with urlopen(request, timeout=90) as response:
        payload = json.load(response)
    ids = {
        int(pitcher["mlb_id"])
        for pitcher in payload.get("pitchers", [])
        if pitcher.get("mlb_id") is not None
    }
    if not ids or len(ids) > 250:
        raise ValueError(f"Unexpected public pitcher list size: {len(ids)}")
    return ids


def write_export(records, destination):
    """Export only known, plausible local xSLG values and matching event identities."""
    destination = Path(destination)
    destination.parent.mkdir(parents=True, exist_ok=True)
    count = 0
    with gzip.open(destination, mode="wt", encoding="utf-8", newline="") as stream:
        writer = csv.writer(stream)
        writer.writerow(["pitch_id", "pitcher_id", "game_date", "events", "estimated_slg"])
        for row in records:
            value = row["estimated_slg"]
            if value is None:
                continue
            value = float(value)
            if not 0 <= value <= 4:
                raise ValueError(f"Invalid xSLG for pitch {row['pitch_id']}: {value}")
            writer.writerow(
                [
                    row["pitch_id"],
                    row["pitcher_id"],
                    row["game_date"].isoformat(),
                    row["events"],
                    f"{value:.9g}",
                ]
            )
            count += 1
    return count


def main():
    parser = argparse.ArgumentParser(
        description="Export local xSLG values for safe public cohort reconciliation."
    )
    picker = parser.add_mutually_exclusive_group(required=True)
    picker.add_argument("--pitcher", type=int, help="One pitcher by MLB ID")
    picker.add_argument("--all", action="store_true", help="All currently public pitchers")
    parser.add_argument("--season", type=int, default=2026)
    parser.add_argument("--public-url", default=PUBLIC_URL)
    parser.add_argument("--output", type=Path)
    args = parser.parse_args()

    load_dotenv()

    from sqlalchemy import select

    from app import create_app
    from app.extensions import db
    from app.models import Game, Pitch

    ids = (
        public_pitcher_ids(args.season, args.public_url)
        if args.all
        else {args.pitcher}
    )
    destination = args.output or Path(
        f"outputs/local_xslg_public_pool_{args.season}.csv.gz"
    )
    application = create_app()
    with application.app_context():
        records = db.session.execute(
            select(
                Pitch.pitch_id.label("pitch_id"),
                Pitch.pitcher_id.label("pitcher_id"),
                Game.game_date.label("game_date"),
                Pitch.events.label("events"),
                Pitch.estimated_slg.label("estimated_slg"),
            )
            .select_from(Pitch)
            .join(Game, Game.game_pk == Pitch.game_pk)
            .where(
                Game.season == args.season,
                Pitch.pitcher_id.in_(ids),
                Pitch.estimated_slg.is_not(None),
                Pitch.events.is_not(None),
                Pitch.events != "",
            )
            .order_by(Pitch.pitcher_id, Pitch.pitch_id)
        ).mappings().yield_per(2000)
        count = write_export(records, destination)
    if not count:
        raise ValueError("No local expected SLG values found for selected pitcher(s).")
    print(f"Exported {count:,} existing xSLG values for {len(ids)} pitcher(s).")
    print(f"File: {destination.resolve()}")
    print("Read-only export. Neither database was modified.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
