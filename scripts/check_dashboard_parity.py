"""Compare local full-MLB PostgreSQL profiles with the public 50-pitcher cohort.

Read-only. Uses the same Flask route in both environments, so it audits
every numerical field exposed by the profile API, not just the visible RV cards.

    python -m scripts.check_dashboard_parity --pitcher 605400
    python -m scripts.check_dashboard_parity --pitcher 605400 --by-game
    python -m scripts.check_dashboard_parity --all --season 2026

No local database values or credentials are uploaded. The script downloads
publicly exposed JSON and compares it with local Flask/SQL queries.
"""

from __future__ import annotations

import argparse
import json
import math
import sys
import time
from pathlib import Path
from urllib.error import HTTPError, URLError
from urllib.parse import urlencode
from urllib.request import Request, urlopen

DEFAULT_PUBLIC_URL = "https://mlb-pitch-intelligence.onrender.com"
SKIP_FIELDS = {
    "reference_fangraphs_updated",
    "reference_savant_updated",
    "updated_at",
}


def _remote_json(url):
    last_error = None
    for attempt in range(3):
        try:
            request = Request(url, headers={"User-Agent": "MLB-Pitcher-Dashboard-Parity/1.0"})
            with urlopen(request, timeout=75) as response:
                return json.load(response)
        except (HTTPError, URLError, TimeoutError, ValueError) as exc:
            last_error = exc
            if attempt < 2:
                time.sleep(2 * (attempt + 1))
    raise RuntimeError(f"Public dashboard request failed: {url}: {last_error}")


def _local_json(client, path):
    response = client.get(path)
    if response.status_code != 200:
        raise RuntimeError(f"Local profile returned HTTP {response.status_code}: {path}")
    return response.get_json()


def _path(pitcher_id, season, *, day=None):
    params = {"season": season}
    if day is not None:
        params.update({"date_from": day.isoformat(), "date_to": day.isoformat()})
    return f"/api/v1/pitchers/{pitcher_id}/profile?{urlencode(params)}"


def _flatten(value, prefix=""):
    """Stable path identifiers prevent arbitrary row ordering from producing false drift."""
    if isinstance(value, dict):
        for key, item in value.items():
            if key in SKIP_FIELDS or key.endswith("_updated_at"):
                continue
            yield from _flatten(item, f"{prefix}.{key}" if prefix else str(key))
    elif isinstance(value, list):
        keyed = {}
        for item in value:
            if not isinstance(item, dict):
                break
            key = next(
                (
                    str(item[name])
                    for name in ("pitch_type", "batter_side", "pitch_a", "date")
                    if name in item and item[name] is not None
                ),
                None,
            )
            if key is None or key in keyed:
                break
            keyed[key] = item
        if len(keyed) == len(value):
            for key in sorted(keyed):
                yield from _flatten(keyed[key], f"{prefix}[{key}]")
        else:
            for index, item in enumerate(value):
                yield from _flatten(item, f"{prefix}[{index}]")
    else:
        yield prefix, value


def compare_profiles(local, public, tolerance=1e-7):
    sections = (
        "pitcher",
        "sample",
        "overall",
        "arsenal",
        "platoon_splits",
        "pitch_separation",
        "pitch_tunneling",
        "fangraphs",
    )
    local_fields = dict(
        pair for key in sections if key in local
        for pair in _flatten(local[key], key)
    )
    public_fields = dict(
        pair for key in sections if key in public
        for pair in _flatten(public[key], key)
    )
    differences = []
    for key in sorted(local_fields.keys() | public_fields.keys()):
        a = local_fields.get(key, "<absent>")
        b = public_fields.get(key, "<absent>")
        if isinstance(a, (float, int)) and isinstance(b, (float, int)) and not (
            isinstance(a, bool) or isinstance(b, bool)
        ):
            equal = math.isclose(a, b, rel_tol=0, abs_tol=tolerance)
        else:
            equal = a == b
        if not equal:
            differences.append({"field": key, "local": a, "public": b})
    return differences


def compare_one(client, pitcher_id, season, public_url, tolerance, *, day=None):
    path = _path(pitcher_id, season, day=day)
    local = _local_json(client, path)
    public = _remote_json(public_url.rstrip("/") + path)
    differences = compare_profiles(local, public, tolerance=tolerance)
    return {
        "pitcher_id": pitcher_id,
        "pitcher": local.get("pitcher", {}).get("name"),
        "date": day.isoformat() if day else None,
        "local_pitches": local.get("sample", {}).get("pitches"),
        "public_pitches": public.get("sample", {}).get("pitches"),
        "different_fields": len(differences),
        "differences": differences,
    }


def main():
    parser = argparse.ArgumentParser(description="Read-only local vs. public pitcher profile audit.")
    parser.add_argument("--season", type=int, default=2026)
    parser.add_argument("--pitcher", type=int, default=605400, help="MLB ID; defaults to Aaron Nola")
    parser.add_argument("--all", action="store_true", help="Check each publicly listed pitcher")
    parser.add_argument("--by-game", action="store_true", help="Identify differing game dates for one pitcher")
    parser.add_argument("--public-url", default=DEFAULT_PUBLIC_URL)
    parser.add_argument("--max-print", type=int, default=24)
    parser.add_argument("--output", type=Path, help="Optional local JSON report path")
    args = parser.parse_args()
    if args.all and args.by_game:
        parser.error("--by-game is limited to an individual pitcher")

    from dotenv import load_dotenv

    load_dotenv()
    from app import create_app
    from app.extensions import db
    from app.models import Game, Pitch
    from sqlalchemy import select

    application = create_app()
    report = {"season": args.season, "public_url": args.public_url, "results": []}
    with application.app_context():
        client = application.test_client()
        if args.all:
            public_index = _remote_json(
                args.public_url.rstrip("/") + f"/api/v1/pitchers?season={args.season}"
            )
            pitcher_ids = sorted(player["mlb_id"] for player in public_index["pitchers"])
        else:
            pitcher_ids = [args.pitcher]

        for pitcher_id in pitcher_ids:
            try:
                result = compare_one(client, pitcher_id, args.season, args.public_url, 1e-7)
            except RuntimeError as exc:
                result = {"pitcher_id": pitcher_id, "error": str(exc)}
            report["results"].append(result)
            name = result.get("pitcher") or str(pitcher_id)
            if "error" in result:
                print(f"{name}: ERROR: {result['error']}")
                continue
            print(
                f"{name}: local {result['local_pitches']} pitches, "
                f"public {result['public_pitches']} pitches, "
                f"{result['different_fields']} differing fields"
            )
            for diff in result["differences"][: args.max_print]:
                print(f"  {diff['field']}: local={diff['local']!r}, public={diff['public']!r}")
            remaining = result["different_fields"] - args.max_print
            if remaining > 0:
                print(f"  ... {remaining} more fields (use --output to retain all)")

        if args.by_game:
            dates = db.session.scalars(
                select(Game.game_date)
                .join(Pitch, Game.game_pk == Pitch.game_pk)
                .where(Pitch.pitcher_id == args.pitcher, Game.season == args.season)
                .distinct()
                .order_by(Game.game_date)
            ).all()
            games = []
            for game_day in dates:
                try:
                    game = compare_one(
                        client, args.pitcher, args.season, args.public_url, 1e-7, day=game_day
                    )
                except RuntimeError as exc:
                    game = {"date": game_day.isoformat(), "error": str(exc)}
                if game.get("different_fields") or "error" in game:
                    games.append(game)
                    print(
                        f"  {game_day}: {game.get('different_fields', 'ERROR')} mismatched fields"
                    )
            report["game_differences"] = games
    if args.output:
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(json.dumps(report, indent=2, default=str), encoding="utf-8")
        print(f"Saved complete read-only comparison: {args.output}")
    return 1 if any(
        result.get("different_fields") or result.get("error")
        for result in report["results"]
    ) else 0


if __name__ == "__main__":
    sys.exit(main())
