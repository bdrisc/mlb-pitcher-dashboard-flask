"""Archive published season leaderboards and plan candidate-only metric rows."""

from __future__ import annotations

import argparse
import csv
import hashlib
import io
import json
from math import isfinite
from pathlib import Path
from urllib.parse import urlencode

from app.services.fangraphs_fetch import normalize_response
from app.services.fangraphs_stuff import CATEGORIES, PITCH_CATEGORIES
from app.services.published_pitching_fetch import (
    FANGRAPHS_ENDPOINT,
    SAVANT_ACTIVE_SPIN_ENDPOINT,
    SAVANT_ENDPOINT,
    normalize_fangraphs,
    normalize_savant_active_spin_csv,
    normalize_savant_csv,
)
from app.services.savant_active_spin import SAVANT_SPIN_FIELDS
from scripts.acquire_future_savant import MAX_BYTES, download, timestamp
from scripts.reconcile_future_sources import read_staged_sources
from scripts.rehearse_snapshot_release import ReleaseError, require, save, sha

GRADE_FIELDS = ("stuff_plus", "location_plus", "pitching_plus")
RATE_FIELDS = ("FIP", "xFIP", "SIERA")


def specs(season):
    fg = dict(
        pos="all",
        stats="pit",
        lg="all",
        qual=0,
        season=season,
        season1=season,
        ind=0,
        month=0,
        team=0,
        rost=0,
        pageitems=10000,
        pagenum=1,
    )
    return {
        "fangraphs_grades": (FANGRAPHS_ENDPOINT, {**fg, "type": 36}, "json"),
        "fangraphs_rates": (FANGRAPHS_ENDPOINT, {**fg, "type": 8, "hand": ""}, "json"),
        "savant_xera": (
            SAVANT_ENDPOINT,
            dict(
                type="pitcher",
                year=season,
                position="",
                team="",
                filterType="pa",
                min=0,
                csv="true",
            ),
            "csv",
        ),
        "savant_spin": (
            SAVANT_ACTIVE_SPIN_ENDPOINT,
            dict(year=f"{season}_spin-based", min=1, hand="", csv="true"),
            "csv",
        ),
    }


def digest(data):
    return hashlib.sha256(data).hexdigest()


def integer(value):
    require(
        not isinstance(value, bool) and str(value).isdigit() and int(value) > 0,
        "Invalid player identity.",
    )
    return int(value)


def metric(value, *, percent=False):
    if value is None or str(value).strip() in ("", "-", "—"):
        return None
    require(not isinstance(value, bool), "Invalid boolean metric.")
    value = float(str(value).strip().removesuffix("%") if percent else value)
    require(isfinite(value), "Nonfinite published metric.")
    require(not percent or 0 <= value <= 100, "Invalid active-spin percentage.")
    return value


def strict_json(data):
    def pairs(items):
        result = {}
        for key, value in items:
            require(key not in result, "Duplicate JSON key.")
            result[key] = value
        return result

    def invalid(value):
        raise ReleaseError(f"Invalid JSON constant: {value}")

    return json.loads(data, object_pairs_hook=pairs, parse_constant=invalid)


def fg_rows(data, season, grades):
    payload = strict_json(data)
    rows = payload["data"]
    require(
        isinstance(rows, list)
        and bool(rows)
        and type(payload["totalCount"]) is int
        and len(rows) == payload["totalCount"]
        and len(rows) < 10000,
        "Incomplete or truncated FanGraphs leaderboard.",
    )
    # Reuse established source-schema validation before strict normalization.
    if grades:
        normalize_response(payload, season)
    else:
        normalize_fangraphs(payload, season)
    result, unmapped, fg_ids = {}, [], set()
    for row in rows:
        require(
            row.get("Season", row.get("season")) == season,
            "FanGraphs season missing or mismatched.",
        )
        fg_id = integer(row["playerid"])
        require(fg_id not in fg_ids, "Duplicate FanGraphs player ID.")
        fg_ids.add(fg_id)
        if row.get("xMLBAMID") in (None, "", 0, "0"):
            unmapped.append(fg_id)
            continue
        pid = integer(row["xMLBAMID"])
        require(pid not in result, "Duplicate FanGraphs MLB ID.")
        if grades:
            values = {"ALL": [metric(row[k]) for k in ("sp_stuff", "sp_location", "sp_pitching")]}
            for code in CATEGORIES:
                tag = "FF" if code == "FA" else code
                values[code] = [metric(row.get(f"sp_{prefix}_{tag}")) for prefix in ("s", "l", "p")]
        else:
            values = {field: metric(row[field]) for field in RATE_FIELDS}
        result[pid] = (fg_id, values)
    require(bool(result), "No mapped FanGraphs rows.")
    return result, sorted(unmapped)


def csv_rows(data, season, spin):
    reader = csv.DictReader(io.StringIO(data.decode("utf-8-sig"), newline=""))
    header = reader.fieldnames or []
    require(len(header) == len(set(header)), "Duplicate CSV header.")
    rows = list(reader)
    require(
        bool(rows)
        and all(None not in row and all(v is not None for v in row.values()) for row in rows),
        "Empty or malformed leaderboard CSV.",
    )
    if spin:
        normalize_savant_active_spin_csv(data, season)
    else:
        normalize_savant_csv(data, season)
    result = {}
    for row in rows:
        pid = integer(row["entity_id" if spin else "player_id"])
        require(pid not in result, "Duplicate Savant player ID.")
        if spin:
            values = {
                code: metric(row[field], percent=True) for field, code in SAVANT_SPIN_FIELDS.items()
            }
        else:
            values = metric(row["xera"])
            require(values is None or values >= 0, "Negative published xERA.")
        result[pid] = values
    # Spin exports may omit year; provenance then binds the requested method/year only.
    return result, "year" in header


def normalize(bodies, season, staged):
    grades, unmapped_grades = fg_rows(bodies["fangraphs_grades"], season, True)
    rates, unmapped_rates = fg_rows(bodies["fangraphs_rates"], season, False)
    xera, _ = csv_rows(bodies["savant_xera"], season, False)
    spin, spin_year = csv_rows(bodies["savant_spin"], season, True)
    crosswalk = {}
    for source in (grades, rates):
        for pid, (fg_id, _) in source.items():
            require(
                fg_id not in crosswalk or crosswalk[fg_id] == pid,
                "FanGraphs ID maps to multiple MLB IDs.",
            )
            crosswalk[fg_id] = pid
    require(
        all(grades[pid][0] == rates[pid][0] for pid in grades.keys() & rates.keys()),
        "Conflicting FanGraphs identities across leaderboards.",
    )
    grade_rows, rate_rows, spin_rows, gaps = [], [], [], []
    for pid in sorted(staged):
        expected_codes = sorted({row["pitch_type"] for row in staged[pid].values()})
        fg_id, values = grades.get(pid, (None, {}))
        for code in ("ALL", *CATEGORIES):
            triple = values.get(code, [None] * 3)
            if any(v is not None for v in triple):
                grade_rows.append(
                    dict(
                        mlb_id=pid,
                        season=season,
                        fangraphs_id=str(fg_id),
                        category=code,
                        **dict(zip(GRADE_FIELDS, triple, strict=True)),
                    )
                )
        expected_grades = {
            "ALL",
            *(PITCH_CATEGORIES[c] for c in expected_codes if c in PITCH_CATEGORIES),
        }
        for code in sorted(expected_grades):
            for field, value in zip(GRADE_FIELDS, values.get(code, [None] * 3), strict=True):
                if value is None:
                    gaps.append([pid, "fangraphs_grades", code, field])
        rate_id, rate = rates.get(pid, (None, {}))
        row = dict(
            mlb_id=pid,
            season=season,
            batter_side="ALL",
            fangraphs_id=str(rate_id) if rate_id is not None else None,
            fip=rate.get("FIP"),
            xfip=rate.get("xFIP"),
            siera=rate.get("SIERA"),
            xera=xera.get(pid),
        )
        for field in ("fip", "xfip", "siera", "xera"):
            if row[field] is None:
                gaps.append([pid, "published_rates", "ALL", field])
        if any(row[field] is not None for field in ("fip", "xfip", "siera", "xera")):
            rate_rows.append(row)
        for code, value in sorted(spin.get(pid, {}).items()):
            if value is not None:
                spin_rows.append(
                    dict(mlb_id=pid, season=season, pitch_type=code, active_spin_pct=value)
                )
        for code in expected_codes:
            if code in SAVANT_SPIN_FIELDS.values() and spin.get(pid, {}).get(code) is None:
                gaps.append([pid, "savant_spin", code, "active_spin_pct"])
    coverage = {}
    for name, source in (
        ("fangraphs_grades", grades),
        ("fangraphs_rates", rates),
        ("savant_xera", xera),
        ("savant_spin", spin),
    ):
        coverage[name] = {
            "source_pitchers": len(source),
            "matched_pitchers": len(set(source) & set(staged)),
            "missing_staged_pitchers": sorted(set(staged) - set(source)),
            "outside_staging_pitchers": sorted(set(source) - set(staged)),
        }
    return {
        "coverage_review_required": True,
        "identity_review_required": True,
        "coverage": coverage,
        "unmapped_fangraphs_grades": unmapped_grades,
        "unmapped_fangraphs_rates": unmapped_rates,
        "spin_season_in_response": spin_year,
        "missing_values": gaps,
        "fangraphs_stuff": grade_rows,
        "published_pitching_metrics": rate_rows,
        "savant_active_spin": spin_rows,
    }


def synthetic_bodies(season):
    pid = 2000000010
    row = dict(
        playerid=9000001,
        xMLBAMID=pid,
        Season=season,
        sp_stuff=112,
        sp_location=104,
        sp_pitching=109,
        sp_s_FF=115,
        sp_l_FF=103,
        sp_p_FF=110,
        FIP=3.2,
        xFIP=3.5,
        SIERA=3.4,
    )
    fg = json.dumps({"data": [row], "totalCount": 1}).encode()
    spin = io.StringIO()
    writer = csv.DictWriter(spin, fieldnames=["entity_id", "year", *SAVANT_SPIN_FIELDS])
    writer.writeheader()
    writer.writerow(
        {"entity_id": pid, "year": f"{season}_spin-based", "active_spin_fourseam": "95.5%"}
    )
    return {
        "fangraphs_grades": fg,
        "fangraphs_rates": fg,
        "savant_xera": f"player_id,year,xera\n{pid},{season},3.1\n".encode(),
        "savant_spin": spin.getvalue().encode(),
    }


def build_report(report, staged, raw, records, staging_sha, correction_sha):
    season = report["season"]
    expected = specs(season)
    require(set(records) == set(expected), "Missing or extra source responses.")
    bodies = {}
    for kind, (endpoint, params, suffix) in expected.items():
        record = records[kind]
        name = f"{kind}.{suffix}"
        require(
            record["file"] == name
            and record["url"] == endpoint + "?" + urlencode(params)
            and record["parameters"] == params
            and record["synthetic"] is report["synthetic"]
            and record["http_status"] == 200
            and json.loads((raw / f"{name}.meta.json").read_bytes()) == record,
            "Source provenance mismatch.",
        )
        data = (raw / name).read_bytes()
        require(
            0 < len(data) <= MAX_BYTES
            and len(data) == record["bytes"]
            and digest(data) == record["sha256"],
            "Raw leaderboard checksum mismatch.",
        )
        bodies[kind] = data
    return {
        "schema": 1,
        "status": "LEADERBOARD_EVIDENCE_PASS_NOT_APPLIED",
        "season": season,
        "synthetic": report["synthetic"],
        "staging_report_sha256": staging_sha,
        "correction_report_sha256": correction_sha,
        "responses": records,
        "production_write_allowed": False,
        **normalize(bodies, season, staged),
    }


def acquire(report, staged, output, staging_sha, correction_sha, fetch=download):
    output.mkdir(parents=True, exist_ok=False)
    raw = output / "raw"
    raw.mkdir()
    records = {}
    fixtures = synthetic_bodies(report["season"]) if report["synthetic"] else None
    for kind, (endpoint, params, suffix) in specs(report["season"]).items():
        url = endpoint + "?" + urlencode(params)
        started = timestamp()
        data, status, content_type = (
            (fixtures[kind], 200, suffix) if fixtures is not None else fetch(url)
        )
        require(status == 200 and 0 < len(data) <= MAX_BYTES, "Invalid HTTP response.")
        name = f"{kind}.{suffix}"
        with (raw / name).open("xb") as handle:
            handle.write(data)
        record = dict(
            file=name,
            url=url,
            parameters=params,
            started_utc=started,
            received_utc=timestamp(),
            http_status=status,
            content_type=content_type,
            synthetic=report["synthetic"],
            bytes=len(data),
            sha256=digest(data),
        )
        save(raw / f"{name}.meta.json", record)
        records[kind] = record
        print(f"Archived {kind}", flush=True)
    result = build_report(report, staged, raw, records, staging_sha, correction_sha)
    save(output / "leaderboard_evidence.json", result)
    return result


def validate_correction(path, expected_sha, report, staged, staging_sha):
    require(sha(path) == expected_sha, "Correction report checksum mismatch.")
    correction = json.loads(path.read_bytes())
    require(
        correction["schema"] == 1
        and correction["status"] == "CORRECTIONS_PASS_QUARANTINED"
        and correction["season"] == report["season"]
        and correction["synthetic"] is report["synthetic"]
        and correction["staging_report_sha256"] == staging_sha
        and correction["historical_fingerprint"] == report["historical_fingerprint"]
        and correction["patched_pitches"] == sum(map(len, staged.values()))
        and correction["production_write_allowed"] is False,
        "Correction report is not the approved staged candidate.",
    )


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    for name in ("staging-report", "correction-report"):
        parser.add_argument("--" + name, type=Path, required=True)
    for name in ("staging-sha", "correction-sha"):
        parser.add_argument("--" + name, required=True)
    parser.add_argument("--synthetic", action="store_true")
    parser.add_argument("--output", type=Path)
    parser.add_argument("--verify-report", type=Path)
    parser.add_argument("--report-sha")
    args = parser.parse_args()
    try:
        require(bool(args.output) != bool(args.verify_report), "Choose acquisition or replay.")
        report, staged = read_staged_sources(args.staging_report, args.staging_sha)
        require(args.synthetic is report["synthetic"], "Synthetic/real mode mismatch.")
        validate_correction(
            args.correction_report, args.correction_sha, report, staged, args.staging_sha
        )
        if args.verify_report:
            require(sha(args.verify_report) == args.report_sha, "Report checksum mismatch.")
            result = json.loads(args.verify_report.read_bytes())
            rebuilt = build_report(
                report,
                staged,
                args.verify_report.parent / "raw",
                result["responses"],
                args.staging_sha,
                args.correction_sha,
            )
            require(result == rebuilt, "Evidence plan differs from raw archive.")
            path = args.verify_report
            require(sha(path) == args.report_sha, "Report changed during replay.")
        else:
            require(not args.report_sha, "Report checksum applies only to replay.")
            result = acquire(report, staged, args.output, args.staging_sha, args.correction_sha)
            path = args.output / "leaderboard_evidence.json"
        require(
            sha(args.staging_report) == args.staging_sha
            and sha(args.correction_report) == args.correction_sha,
            "Reviewed input changed.",
        )
        for table in ("fangraphs_stuff", "published_pitching_metrics", "savant_active_spin"):
            print(f"{table}: {len(result[table])} planned rows")
        print(f"Missing published values: {len(result['missing_values'])}")
        print(f"Report SHA-256: {sha(path)}")
        print(result["status"])
        print("No database writes or publication performed.")
        return 0
    except Exception as exc:
        print(
            "LEADERBOARD_EVIDENCE_FAILED:",
            str(exc) if isinstance(exc, ValueError) else type(exc).__name__,
        )
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
