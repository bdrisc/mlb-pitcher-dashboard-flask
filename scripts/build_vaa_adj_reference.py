"""Freeze prior-season league VAAAdj expectations and audit the following season."""

from __future__ import annotations

import gzip
import hashlib
import io
import json
from concurrent.futures import ThreadPoolExecutor
from datetime import date, timedelta
from pathlib import Path
from urllib.parse import urlencode
from urllib.request import Request, urlopen

import numpy as np
import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
CACHE = ROOT / "data/cache/vaa_adj_reference"
COLUMNS = [
    "game_pk",
    "at_bat_number",
    "pitch_number",
    "pitcher",
    "game_year",
    "game_date",
    "game_type",
    "pitch_type",
    "plate_z",
    "vz0",
    "vy0",
    "az",
    "ay",
]


def fetch(window):
    year, first, last = window
    path = CACHE / f"{year}_{first}_{last}.csv.gz"
    if path.exists():
        try:
            pd.read_csv(path, usecols=COLUMNS)
            return path
        except (EOFError, OSError, ValueError):
            path.unlink()
    params = {
        "all": "true",
        "type": "details",
        "player_type": "pitcher",
        "hfSea": f"{year}|",
        "hfGT": "R|",
        "game_date_gt": first.isoformat(),
        "game_date_lt": last.isoformat(),
        "min_pitches": 0,
        "min_results": 0,
    }
    request = Request(
        "https://baseballsavant.mlb.com/statcast_search/csv?" + urlencode(params),
        headers={"User-Agent": "Mozilla/5.0"},
    )
    for attempt in range(3):
        try:
            with urlopen(request, timeout=60) as response:
                frame = pd.read_csv(io.BytesIO(response.read()), usecols=lambda c: c in COLUMNS)
            if set(COLUMNS) - set(frame):
                raise ValueError("Missing required fields in Savant response")
            if len(frame) >= 30000:
                raise ValueError("Savant response may be truncated")
            if not frame.empty:
                dates = pd.to_datetime(frame.game_date).dt.date
                if (
                    not dates.between(first, last).all()
                    or not (frame.game_year == year).all()
                    or not (frame.game_type == "R").all()
                ):
                    raise ValueError("Savant ignored the season/date/game-type scope")
            temporary = path.with_suffix(".tmp")
            temporary.write_bytes(gzip.compress(frame.to_csv(index=False).encode(), mtime=0))
            temporary.replace(path)
            print(f"Cached {year} {first} to {last}: {len(frame):,} rows", flush=True)
            return path
        except Exception:
            if attempt == 2:
                raise


def prepare(frame):
    f = frame.copy()
    fields = ["plate_z", "vz0", "vy0", "az", "ay"]
    for key in fields:
        f[key] = pd.to_numeric(f[key], errors="coerce")
    valid = np.isfinite(f[fields]).all(axis=1)
    f = f[valid & f.pitch_type.notna() & (f.vy0 < 0)].copy()
    d = 50 - 17 / 12
    discr = f.vy0**2 - 2 * f.ay * d
    f = f[discr > 0].copy()
    tfront = 2 * d / (-f.vy0 + np.sqrt(f.vy0**2 - 2 * f.ay * d))
    vyfront = f.vy0 + f.ay * tfront
    f["vaa"] = np.degrees(np.arctan2(f.vz0 + f.az * tfront, -vyfront))
    f["plate_z_front"] = f.plate_z
    middle = f.game_year >= 2026
    tmiddle = 2 * (50 - 17 / 24) / (-f.vy0 + np.sqrt(f.vy0**2 - 2 * f.ay * (50 - 17 / 24)))
    f.loc[middle, "plate_z_front"] += (
        f.vz0 * (tfront - tmiddle) + 0.5 * f.az * (tfront**2 - tmiddle**2)
    )[middle]
    return f[np.isfinite(f[["vaa", "plate_z_front"]]).all(axis=1)]


def metrics(actual, predicted):
    residual = actual - predicted
    return dict(
        n=len(actual),
        bias=float(residual.mean()),
        mae=float(np.abs(residual).mean()),
        rmse=float(np.sqrt(np.mean(residual**2))),
    )


def main():
    CACHE.mkdir(parents=True, exist_ok=True)
    windows = []
    for year in (2025, 2026):
        start, end = date(year, 3, 15), date(year, 10, 1)
        while start <= end:
            last = min(start + timedelta(days=2), end)
            windows.append((year, start, last))
            start = last + timedelta(days=1)
    with ThreadPoolExecutor(max_workers=4) as pool:
        paths = list(pool.map(fetch, windows))
    frames = {}
    for year in (2025, 2026):
        parts = []
        for path in paths:
            if path.name.startswith(str(year)):
                part = pd.read_csv(path)
                if not part.empty:
                    parts.append(part)
        frames[year] = pd.concat(parts, ignore_index=True)
    for year, f in frames.items():
        if f.duplicated(["game_pk", "at_bat_number", "pitch_number"]).any():
            raise ValueError(f"Duplicate pitch IDs in {year} reference")
    verified_totals = {}
    for year, frame in frames.items():
        path = CACHE / f"official_{year}.json"
        if not path.is_file():
            params = {
                "player_type": "pitcher",
                "hfSea": f"{year}|",
                "hfGT": "R|",
                "group_by": "league",
                "outputFormat": "json",
                "all": "true",
                "min_pitches": 0,
                "min_results": 0,
                "game_date_gt": f"{year}-03-15",
                "game_date_lt": f"{year}-10-01",
            }
            request = Request(
                "https://baseballsavant.mlb.com/statcast_search?" + urlencode(params),
                headers={"User-Agent": "Mozilla/5.0"},
            )
            with urlopen(request, timeout=60) as response:
                path.write_bytes(response.read())
        aggregate = json.loads(path.read_text())
        # Current Savant aggregates distinguish physical pitches and events and
        # do not expose every automatic-call CSV row in total_pitches. Anchor
        # CSV coverage to the prior independently verified full-season audit,
        # and independently recheck its physical count against Savant today.
        audit_path = ROOT / "data/haaaa_validation_2026.json"
        audit_bytes = audit_path.read_bytes()
        audited = json.loads(audit_bytes)["verified_source_counts"][str(year)]
        physical = sum(int(row["pitches"]) for row in aggregate)
        classified = int(frame.pitch_type.notna().sum())
        if (
            len(frame) != audited["events"]
            or physical != audited["physical_pitches"]
            or classified != audited["classified_pitches"]
        ):
            raise ValueError(f"{year} source coverage differs from the verified full-season audit")
        verified_totals[str(year)] = dict(
            events=len(frame),
            physical_pitches=physical,
            classified_pitches=classified,
            aggregate_total_pitches=sum(int(row["total_pitches"]) for row in aggregate),
            aggregate_num_events=sum(int(row.get("num_events", 0)) for row in aggregate),
            event_count_verification="prior independently verified full-season source audit",
            audit_file="data/haaaa_validation_2026.json",
            audit_sha256=hashlib.sha256(audit_bytes).hexdigest(),
        )
    data = {year: prepare(f) for year, f in frames.items()}
    groups = {}
    validation = {}
    for pitch, f in data[2025].groupby("pitch_type"):
        if len(f) < 500 or f.pitcher.nunique() < 5:
            continue
        X = np.column_stack((np.ones(len(f)), f.plate_z_front))
        beta, _, rank, _ = np.linalg.lstsq(X, f.vaa, rcond=None)
        if rank != 2:
            continue
        group = dict(
            coefficients=beta.tolist(),
            n=len(f),
            pitchers=int(f.pitcher.nunique()),
            plate_z_range=[float(f.plate_z_front.min()), float(f.plate_z_front.max())],
            train=metrics(f.vaa.to_numpy(), X @ beta),
        )
        key = pitch
        groups[key] = group
        v = data[2026].query("pitch_type == @pitch")
        if len(v):
            predictions = np.column_stack((np.ones(len(v)), v.plate_z_front)) @ beta
            validation[key] = {
                **metrics(v.vaa.to_numpy(), predictions),
                "unadjusted_baseline": metrics(v.vaa.to_numpy(), np.full(len(v), f.vaa.mean())),
            }
    core = dict(
        schema_version=1,
        train_season=2025,
        applies_from_season=2026,
        target="front_plane_vaa_degrees",
        features=["intercept", "plate_z_front"],
        plane_y_ft=17 / 12,
        middle_plane_y_ft=17 / 24,
        min_pitches=500,
        min_pitchers=5,
        groups=groups,
    )
    digest = hashlib.sha256(json.dumps(core, sort_keys=True, allow_nan=False).encode()).hexdigest()
    core["model_id"] = digest
    report = dict(
        model_id=digest,
        verified_source_counts=verified_totals,
        raw_rows={str(y): len(f) for y, f in frames.items()},
        usable_rows={str(y): len(f) for y, f in data.items()},
        validation_season=2026,
        validation=validation,
        sources={p.name: hashlib.sha256(p.read_bytes()).hexdigest() for p in paths},
    )
    (ROOT / "data/vaa_adj_reference_2025.json").write_text(
        json.dumps(core, indent=2, allow_nan=False) + "\n"
    )
    (ROOT / "data/vaa_adj_validation_2026.json").write_text(
        json.dumps(report, indent=2, allow_nan=False) + "\n"
    )
    print(
        "Saved frozen reference:",
        digest,
        "groups:",
        len(groups),
        "rows:",
        report["raw_rows"],
        flush=True,
    )
    n = sum(x["n"] for x in validation.values())
    rmse = np.sqrt(sum(x["n"] * x["rmse"] ** 2 for x in validation.values()) / n)
    baseline = np.sqrt(
        sum(x["n"] * x["unadjusted_baseline"]["rmse"] ** 2 for x in validation.values()) / n
    )
    print(
        "2026 validation n:", n, "RMSE:", rmse, "unadjusted group-mean RMSE:", baseline, flush=True
    )


if __name__ == "__main__":
    main()
