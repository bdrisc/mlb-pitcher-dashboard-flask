"""Bounded FanGraphs leaderboard acquisition, isolated from the web process."""

import json
import sys
from urllib.parse import urlencode
from urllib.request import Request, urlopen

import pandas as pd

from app.services.fangraphs_stuff import CATEGORIES


def normalize_response(payload, season):
    rows = payload.get("data")
    if not isinstance(rows, list) or not rows:
        raise ValueError("FanGraphs returned no leaderboard data.")
    if len(rows) != int(payload.get("totalCount", -1)):
        raise ValueError("FanGraphs returned an incomplete leaderboard; cached data preserved.")
    if not all(
        all(key in row for key in ("sp_stuff", "sp_location", "sp_pitching", "xMLBAMID"))
        for row in rows
    ):
        raise ValueError("FanGraphs leaderboard schema changed.")
    records = []
    for row in rows:
        if row.get("Season") != season:
            raise ValueError("FanGraphs returned an unexpected season.")
        if not row.get("xMLBAMID"):
            continue
        record = {
            "IDfg": row["playerid"],
            "mlb_id": row["xMLBAMID"],
            "Season": season,
            "Stuff+": row["sp_stuff"],
            "Location+": row["sp_location"],
            "Pitching+": row["sp_pitching"],
        }
        for category in CATEGORIES:
            source_category = "FF" if category == "FA" else category
            for prefix, code in (("Stf+", "s"), ("Loc+", "l"), ("Pit+", "p")):
                record[f"{prefix} {category}"] = row.get(f"sp_{code}_{source_category}")
        records.append(record)
    return pd.DataFrame(records)


def fetch_grades(season):
    params = dict(
        pos="all",
        stats="pit",
        lg="all",
        qual=0,
        type=36,
        season=season,
        season1=season,
        ind=0,
        month=0,
        team=0,
        rost=0,
        pageitems=10000,
        pagenum=1,
    )
    request = Request(
        "https://www.fangraphs.com/api/leaders/major-league/data?" + urlencode(params),
        headers={"User-Agent": "MLB-Pitch-Intelligence/1.0", "Accept": "application/json"},
    )
    with urlopen(request, timeout=30) as response:
        payload = json.load(response)
    return normalize_response(payload, season)


if __name__ == "__main__":
    fetch_grades(int(sys.argv[1])).to_csv(sys.argv[2], index=False)
