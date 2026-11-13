"""Fetch public provider-published pitcher rates without using Statcast formulas.

FanGraphs: standard 2026 advanced pitching leaderboard (FIP/xFIP/SIERA).
Baseball Savant: official expected-statistics CSV (xERA).
Network operations run in a bounded subprocess, never during web requests.
"""

from __future__ import annotations

import io
import json
import sys
from urllib.parse import urlencode
from urllib.request import Request, urlopen

import pandas as pd

FANGRAPHS_ENDPOINT = "https://www.fangraphs.com/api/leaders/major-league/data"
SAVANT_ENDPOINT = "https://baseballsavant.mlb.com/leaderboard/expected_statistics"


def _download(url, *, accept, timeout=45):
    request = Request(
        url,
        headers={
            "User-Agent": "Mozilla/5.0 (compatible; MLB-Pitch-Intelligence/1.0)",
            "Accept": accept,
        },
    )
    with urlopen(request, timeout=timeout) as response:
        return response.read()


def normalize_fangraphs(payload, season, side="ALL"):
    rows = payload.get("data")
    count = payload.get("totalCount")
    if not isinstance(rows, list) or not rows or count is None or len(rows) != int(count):
        raise ValueError("FanGraphs returned incomplete or empty pitcher leaderboard results.")
    # The FanGraphs handedness leaderboard can have a narrower column set.
    # Preserve official SIERA when supplied, otherwise leave the split blank.
    fields = ("FIP", "xFIP", "SIERA") if side == "ALL" else ("FIP", "xFIP")
    records = []
    for row in rows:
        returned_season = row.get("Season", row.get("season"))
        if returned_season is not None and int(returned_season) != season:
            raise ValueError("FanGraphs returned the wrong season.")
        if not all(field in row for field in fields):
            raise ValueError("FanGraphs response does not include all official pitching rates.")
        if not row.get("xMLBAMID") and not row.get("playerid"):
            continue
        records.append(
            {
                "mlb_id": row.get("xMLBAMID"),
                "IDfg": row.get("playerid"),
                "Season": season,
                **{field: row[field] for field in fields},
                "SIERA": row.get("SIERA"),
            }
        )
    if not records:
        raise ValueError("FanGraphs did not supply pitcher IDs for its results.")
    return pd.DataFrame(records)


def fetch_fangraphs(season, side="ALL"):
    if side not in ("ALL", "L", "R"):
        raise ValueError("Batter handedness must be ALL, L, or R.")
    params = {
        "pos": "all",
        "stats": "pit",
        "lg": "all",
        "qual": 0,
        "type": 8,
        "season": season,
        "season1": season,
        "ind": 0,
        # FanGraphs' "hand" filters the *pitcher's* throwing arm, NOT the
        # opposing batter. The actual batter-side splits use month=13/14.
        "month": {"ALL": 0, "L": 13, "R": 14}[side],
        "hand": "",
        "team": 0,
        "rost": 0,
        "pageitems": 10000,
        "pagenum": 1,
    }
    body = _download(FANGRAPHS_ENDPOINT + "?" + urlencode(params), accept="application/json")
    return normalize_fangraphs(json.loads(body), season, side)


def normalize_savant_csv(content, season):
    data = pd.read_csv(io.BytesIO(content))
    required = {"player_id", "year", "xera"}
    if not required.issubset(data.columns):
        raise ValueError("Savant expected-statistics CSV is not a pitcher xERA leaderboard.")
    if data.empty or not pd.to_numeric(data["year"], errors="coerce").eq(season).all():
        raise ValueError("Savant returned an empty leaderboard or incorrect season.")
    if data["player_id"].isna().any() or data["player_id"].duplicated().any():
        raise ValueError("Savant expected-statistics CSV has missing or duplicate player IDs.")
    return data


def fetch_savant(season):
    params = {
        "type": "pitcher",
        "year": season,
        "position": "",
        "team": "",
        "filterType": "pa",
        "min": 0,
        "csv": "true",
    }
    csv_bytes = _download(SAVANT_ENDPOINT + "?" + urlencode(params), accept="text/csv")
    return normalize_savant_csv(csv_bytes, season)


def validate_handedness_split(split, overall):
    """Reject upstream endpoints silently ignoring a requested handedness filter."""
    if split.empty or overall.empty:
        raise ValueError("No FanGraphs split results to verify.")
    paired = split.merge(overall, on="mlb_id", suffixes=("_side", "_all"))
    if len(paired) < 10 and "IDfg" in split and "IDfg" in overall:
        # Narrower FanGraphs split exports may omit xMLBAMID but retain playerid.
        paired = split.merge(overall, on="IDfg", suffixes=("_side", "_all"))
    if len(paired) >= 10:
        identical = True
        for field in ("FIP", "xFIP", "SIERA"):
            if f"{field}_side" not in paired or f"{field}_all" not in paired:
                continue
            left = pd.to_numeric(paired[f"{field}_side"], errors="coerce")
            right = pd.to_numeric(paired[f"{field}_all"], errors="coerce")
            if ((left - right).abs() > 1e-6).any():
                identical = False
                break
        if identical:
            raise ValueError(
                "FanGraphs split endpoint appears to ignore handedness; "
                "refusing to label season totals as splits."
            )


def main():
    if len(sys.argv) != 5:
        raise SystemExit("Usage: published-pitching-fetch PROVIDER YEAR SPLIT OUT.csv")
    provider, year, side, output = sys.argv[1:]
    season = int(year)
    if provider == "fangraphs":
        frame = fetch_fangraphs(season, side)
    elif provider == "savant" and side == "ALL":
        frame = fetch_savant(season)
    else:
        raise SystemExit("Unsupported provider/split combination.")
    frame.to_csv(output, index=False)


if __name__ == "__main__":
    main()
