"""Package B: build quarantined season-specific reference artifacts, never publish."""

from __future__ import annotations

import argparse
import csv
import gzip
import hashlib
import io
import json
import os
from pathlib import Path

from sqlalchemy import case, func, select

from app.extensions import db
from app.models import Game, Pitch, Player
from app.services.future_season_references import (
    KINDS,
    approved_weights,
    digest,
    valid_weights,
    validate_entry,
)
from app.services.location_performance import _eligible_contact, _zone_coordinates
from app.services.location_reference import FIELDS, _load_future
from app.services.movement_reference import export_full_league_reference
from scripts import snapshot_integrity as integrity
from scripts.apply_future_corrections import snapshot
from scripts.build_pitch_role_reference import export as export_roles
from scripts.rehearse_snapshot_release import (
    app_for,
    clean_checkout,
    recovery_url,
    require,
    save,
    sha,
)
from scripts.validate_future_release_evidence import input_paths, run, synthetic_inputs

GUTS = "https://www.fangraphs.com/tools/guts?type=cn"
WEIGHT_FIELDS = ("wOBAScale", "w1B", "w2B", "w3B", "wHR")


def parse_coefficients(raw, season):
    reader = csv.DictReader(io.StringIO(raw.decode("utf-8-sig"), newline=""))
    fields = reader.fieldnames or []
    require(
        {"Season", *WEIGHT_FIELDS} <= set(fields) and len(fields) == len(set(fields)),
        "Missing or duplicated Guts coefficient columns.",
    )
    rows = list(reader)
    require(
        all(None not in row and all(v is not None for v in row.values()) for row in rows),
        "Malformed Guts coefficient row.",
    )
    matches = [row for row in rows if row["Season"].strip() == str(season)]
    require(len(matches) == 1, "Require exactly one matching season coefficient row.")
    values = [float(matches[0][key]) for key in WEIGHT_FIELDS]
    require(valid_weights(values), "Invalid Guts coefficients.")
    return values


def coefficient_evidence(raw, season, through):
    return {
        "values": parse_coefficients(raw, season),
        "source": GUTS,
        "source_sha256": hashlib.sha256(raw).hexdigest(),
        "as_of": through,
    }


def physical_scope(season):
    stmt = (
        select(
            func.count(func.distinct(Pitch.pitcher_id)),
            func.count(Pitch.pitch_id),
            func.count(func.distinct(Pitch.pitch_id)),
            func.count(func.distinct(Game.game_pk)),
            func.min(Game.game_date),
            func.max(Game.game_date),
        )
        .select_from(Pitch)
        .join(Game, Game.game_pk == Pitch.game_pk)
        .where(Game.season == season, Game.game_type == "R")
    )
    pitchers, pitches, unique, games, first, last = db.session.execute(stmt).one()
    return [pitchers, pitches, unique, games], first.isoformat(), last.isoformat()


def verify_game_counts(season, approved):
    stmt = (
        select(Game.game_pk, Game.game_type, func.count(Pitch.pitch_id))
        .select_from(Pitch)
        .join(Game, Game.game_pk == Pitch.game_pk)
        .where(Game.season == season)
        .group_by(Game.game_pk, Game.game_type)
    )
    rows = db.session.execute(stmt).all()
    require(all(kind == "R" for _, kind, _ in rows), "Unexpected nonregular games.")
    actual = {str(game): count for game, _, count in rows}
    expected = {game: info["physical_pitches"] for game, info in approved["game_results"].items()}
    require(actual == expected, "Candidate game pitch counts differ from Package A.")


def location_payload(season, coverage, start, through):
    x, y = _zone_coordinates()
    venue = case((func.lower(Pitch.inning_half) == "top", "home"), else_="away")
    dimensions = (
        Game.game_date,
        Pitch.balls,
        Pitch.strikes,
        venue,
        Player.throws,
        Pitch.pitch_type,
        Pitch.batter_side,
        x,
        y,
    )
    stmt = (
        select(
            *dimensions,
            func.count(Pitch.pitch_id),
            func.count(Pitch.estimated_woba),
            func.sum(Pitch.estimated_woba),
            func.count(Pitch.exit_velocity),
            func.sum(Pitch.exit_velocity),
            func.sum(case((Pitch.exit_velocity >= 95, 1), else_=0)),
        )
        .select_from(Pitch)
        .join(Game, Game.game_pk == Pitch.game_pk)
        .join(Player, Player.mlb_id == Pitch.pitcher_id)
        .where(
            Game.season == season,
            Game.game_type == "R",
            Player.throws.in_(("R", "L")),
            func.lower(Pitch.inning_half).in_(("top", "bot", "bottom")),
            *_eligible_contact(),
        )
        .group_by(*dimensions)
        .order_by(*dimensions)
    )
    rows = []
    for (
        day,
        balls,
        strikes,
        home,
        hand,
        code,
        side,
        bx,
        by,
        n,
        wn,
        ws,
        en,
        es,
        hh,
    ) in db.session.execute(stmt):
        rows.append(
            [
                day.isoformat(),
                balls,
                strikes,
                home,
                hand,
                code,
                side,
                bx,
                by,
                n,
                wn,
                str(ws or 0),
                en,
                str(es or 0),
                hh,
            ]
        )
    return {
        "version": 1,
        "season": season,
        "fields": list(FIELDS),
        "physical_coverage": coverage,
        "start": start,
        "through": through,
        "game_types": {"R": coverage[1]},
        "rows": rows,
    }


def write_location(path, payload):
    raw = json.dumps(payload, separators=(",", ":"), allow_nan=False).encode()
    with path.open("xb") as handle:
        handle.write(gzip.compress(raw, mtime=0))
    _load_future(
        str(path),
        digest(path),
        payload["season"],
        payload["start"],
        payload["through"],
        tuple(payload["physical_coverage"]),
    )


def build(args):
    from dotenv import load_dotenv

    load_dotenv()
    clean_checkout()
    for key in tuple(os.environ):
        if key.startswith("PG"):
            os.environ.pop(key)
    historical = integrity.reference_hashes()
    synthetic = args.synthetic_backup is not None
    if synthetic:
        require(not args.inputs and not args.guts_csv, "Synthetic mode forbids real inputs.")
        inputs = synthetic_inputs(args.synthetic_backup)
        package = args.synthetic_backup / "package_a_synthetic_01" / "package_a_report.json"
        package_sha = sha(package)
        revision = "synthetic"
    else:
        require(
            args.inputs
            and sha(args.inputs) == args.inputs_sha
            and args.package_a
            and args.register_commit,
            "Real mode requires reviewed Package A inputs and pinned checksums.",
        )
        inputs = json.loads(args.inputs.read_bytes())
        package = args.package_a
        package_sha = args.package_a_sha
        revision = args.register_commit
    approved = run(inputs, synthetic, revision, verify_report=package, report_sha=package_sha)
    paths = input_paths(inputs, synthetic)
    correction = json.loads(paths["correction"].read_bytes())
    season = approved["season"]
    target = recovery_url(os.environ["DATABASE_URL"], correction["candidate_database"])
    require(target.database.startswith("mlb_release_candidate_"), "Not an isolated candidate.")
    before = snapshot(target, season)
    require(before == correction["candidate_fingerprint"], "Candidate fingerprint changed.")
    scope = json.loads(paths["scope"].read_bytes())
    require(
        scope["season"] == season and season >= 2027,
        "Wrong reference season.",
    )
    args.output.mkdir(parents=True, exist_ok=False)
    app = app_for(target)
    try:
        with app.app_context():
            require(db.engine.url.database == target.database, "Wrong reference database.")
            verify_game_counts(season, approved)
            coverage, start, through = physical_scope(season)
            require(
                coverage[1] == coverage[2] == approved["physical_pitches"]
                and coverage[3] == approved["completed_games"]
                and start >= scope["window"]["start"]
                and through <= scope["window"]["end"],
                "Reference coverage differs from independently replayed evidence.",
            )
            if synthetic:
                raw = b"Season,wOBAScale,w1B,w2B,w3B,wHR\n2027,1.20,0.80,1.20,1.60,2.00\n"
            elif args.guts_csv:
                require(sha(args.guts_csv) == args.guts_sha, "Guts archive checksum differs.")
                require(args.guts_as_of == through, "Coefficient vintage must match candidate.")
                raw = args.guts_csv.read_bytes()
            else:
                raw = None
            coeff = coefficient_evidence(raw, season, through) if raw is not None else None
            if raw is not None:
                with (args.output / "guts_source.csv").open("xb") as handle:
                    handle.write(raw)
            artifacts = {}
            missing = {}
            payload = location_payload(season, coverage, start, through)
            if payload["rows"]:
                path = args.output / KINDS["location"].format(season=season)
                write_location(path, payload)
                artifacts["location"] = {"file": path.name, "sha256": digest(path)}
            else:
                missing["location"] = "No eligible tracked contact."
            if coverage[0] >= 300 and coverage[1] >= 200000:
                path = args.output / KINDS["movement"].format(season=season)
                try:
                    export_full_league_reference(season, path)
                except ValueError as exc:
                    if not str(exc).startswith("Not a full MLB season:"):
                        raise
                    missing["movement"] = "Insufficient eligible movement sample."
                else:
                    artifacts["movement"] = {"file": path.name, "sha256": digest(path)}
            else:
                missing["movement"] = "Insufficient full-league sample."
            if coverage[0] >= 300 and coverage[1] >= 200000 and coverage[3] >= 600:
                path = args.output / KINDS["roles"].format(season=season)
                constants = {season: tuple(coeff["values"])} if coeff else {}
                export_roles(season, path, constants)
                artifacts["roles"] = {"file": path.name, "sha256": digest(path)}
            else:
                missing["roles"] = "Insufficient full-league sample."
    finally:
        with app.app_context():
            db.session.remove()
            db.engine.dispose()
    require(snapshot(target, season) == before, "Reference candidate changed.")
    require(integrity.reference_hashes() == historical, "Historical references changed.")
    clean_checkout()
    input_paths(inputs, synthetic)
    require(sha(package) == package_sha, "Package A evidence changed.")
    if not synthetic:
        require(sha(args.inputs) == args.inputs_sha, "Reviewed input manifest changed.")
        if args.guts_csv:
            require(sha(args.guts_csv) == args.guts_sha, "Guts archive changed.")
    entry = {
        "season": season,
        "synthetic": synthetic,
        "start": start,
        "through": through,
        "scope": "complete_mlb_regular_season_to_date",
        "coverage": coverage,
        "package_a_sha256": package_sha,
        "candidate_fingerprint_sha256": hashlib.sha256(
            json.dumps(before, sort_keys=True, separators=(",", ":")).encode()
        ).hexdigest(),
        "coefficients": coeff,
        "artifacts": artifacts,
    }
    if not synthetic:
        validate_entry(season, entry)
    else:
        require(season not in approved_weights(), "Synthetic weights must never be installed.")
    # This proposed entry is deliberately NOT installed in the application's registry.
    result = {
        "schema": 1,
        "status": (
            "PACKAGE_B_SYNTHETIC_PASS_NOT_APPLIED"
            if synthetic
            else "PACKAGE_B_ARTIFACTS_REVIEW_REQUIRED"
        ),
        "entry": entry,
        "unavailable_references": missing,
        "historical_reference_hashes": historical,
        "candidate_fingerprint": before,
        "production_write_allowed": False,
        "registry_updated": False,
    }
    save(args.output / "package_b_report.json", result)
    print(f"Pitchers, pitches, unique pitches, games: {coverage}")
    print(f"Reference artifacts: {sorted(artifacts)}")
    print(f"Unavailable references: {sorted(missing)}")
    print(result["status"])
    print("No database writes or registry publication performed.")


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--synthetic-backup", type=Path)
    parser.add_argument("--inputs", type=Path)
    parser.add_argument("--inputs-sha")
    parser.add_argument("--package-a", type=Path)
    parser.add_argument("--package-a-sha")
    parser.add_argument("--register-commit")
    parser.add_argument("--guts-csv", type=Path)
    parser.add_argument("--guts-sha")
    parser.add_argument("--guts-as-of")
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    try:
        require(bool(args.synthetic_backup) != bool(args.inputs), "Choose synthetic or real mode.")
        build(args)
        return 0
    except Exception as exc:
        print("PACKAGE_B_FAILED:", str(exc) if isinstance(exc, ValueError) else type(exc).__name__)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
