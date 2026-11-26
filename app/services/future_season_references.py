"""Explicitly reviewed future-season metric artifacts; never fall back to a cohort."""

from __future__ import annotations

import json
import re
from datetime import date
from functools import lru_cache
from hashlib import sha256
from math import isfinite
from pathlib import Path

DATA = Path(__file__).resolve().parents[2] / "data"
REGISTRY = DATA / "future_season_references.json"
KINDS = {
    "location": "league_location_{season}.json.gz",
    "movement": "league_movement_{season}.csv.gz",
    "roles": "league_pitch_roles_{season}.json",
}


def digest(path):
    raw = path.read_bytes()
    if path.suffix != ".gz":
        raw = raw.replace(b"\r\n", b"\n")
    return sha256(raw).hexdigest()


def is_digest(value):
    return isinstance(value, str) and re.fullmatch(r"[0-9a-f]{64}", value) is not None


def valid_weights(values):
    return (
        isinstance(values, (tuple, list))
        and len(values) == 5
        and all(type(v) in (int, float) and isfinite(v) and 0 < v < 5 for v in values)
        and values[1] < values[2] < values[3] < values[4]
    )


def validate_entry(season, entry):
    if type(season) is not int or season < 2027:
        raise ValueError("Only future seasons may enter the registry.")
    first = date.fromisoformat(entry["start"])
    last = date.fromisoformat(entry["through"])
    coverage = entry["coverage"]
    if (
        entry["season"] != season
        or entry["synthetic"] is not False
        or first.year != season
        or last.year != season
        or first > last
        or entry["start"] != first.isoformat()
        or entry["through"] != last.isoformat()
        or entry["scope"] != "complete_mlb_regular_season_to_date"
        or not is_digest(entry["package_a_sha256"])
        or not is_digest(entry["candidate_fingerprint_sha256"])
        or len(coverage) != 4
        or any(type(n) is not int or n <= 0 for n in coverage)
        or coverage[1] != coverage[2]
        or coverage[0] > coverage[1]
        or coverage[3] > coverage[1]
    ):
        raise ValueError("Invalid reviewed season scope or coverage.")
    coefficients = entry.get("coefficients")
    if coefficients is not None and (
        not valid_weights(coefficients["values"])
        or not is_digest(coefficients["source_sha256"])
        or coefficients["source"] != "https://www.fangraphs.com/tools/guts?type=cn"
        or date.fromisoformat(coefficients["as_of"]).year != season
        or coefficients["as_of"] != entry["through"]
    ):
        raise ValueError("Invalid season-specific coefficient vintage.")
    for kind, record in entry["artifacts"].items():
        if kind not in KINDS or (
            record["file"] != KINDS[kind].format(season=season)
            or not is_digest(record["sha256"])
        ):
            raise ValueError("Invalid reference artifact identity.")
    return entry


@lru_cache(maxsize=4)
def _registry(path, modified_ns):
    data = json.loads(Path(path).read_bytes())
    if data["schema"] != 1 or not isinstance(data["seasons"], dict):
        raise ValueError("Invalid future season registry.")
    result = {}
    for key, entry in data["seasons"].items():
        season = int(key)
        if key != str(season):
            raise ValueError("Noncanonical registry year.")
        result[season] = validate_entry(season, entry)
    return result


def entries():
    try:
        return _registry(str(REGISTRY), REGISTRY.stat().st_mtime_ns)
    except (OSError, ValueError, TypeError, KeyError, OverflowError, AttributeError):
        return {}


def approved_weights():
    return {
        season: tuple(entry["coefficients"]["values"])
        for season, entry in entries().items()
        if entry.get("coefficients") is not None
    }


@lru_cache(maxsize=32)
def _digest(path, modified_ns, size):
    return digest(Path(path))


def artifact(season, kind):
    entry = entries().get(season)
    if entry is None or kind not in entry["artifacts"]:
        return None
    record = entry["artifacts"][kind]
    path = DATA / record["file"]
    try:
        info = path.stat()
        if _digest(str(path), info.st_mtime_ns, info.st_size) == record["sha256"]:
            return path, entry
    except OSError:
        pass
    return None
