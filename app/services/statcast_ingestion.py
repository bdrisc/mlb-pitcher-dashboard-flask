"""Validate, transform, and transactionally ingest MLB Statcast CSV exports."""

from __future__ import annotations

import hashlib
from collections.abc import Iterable
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import pandas as pd
from sqlalchemy import func, select
from sqlalchemy.dialects.postgresql import insert as postgresql_insert
from sqlalchemy.dialects.sqlite import insert as sqlite_insert

from app.extensions import db
from app.models import Game, IngestionRun, Pitch, Player
from app.services.pitch_data import PITCH_NAME_MAP

REQUIRED_COLUMNS = {
    "game_date",
    "game_pk",
    "at_bat_number",
    "pitch_number",
    "pitch_type",
    "player_name",
    "pitcher",
    "batter",
    "stand",
    "p_throws",
    "balls",
    "strikes",
    "description",
    "type",
    "home_team",
    "away_team",
}

OPTIONAL_COLUMNS = [
    "game_type",
    "inning",
    "inning_topbot",
    "outs_when_up",
    "pitch_name",
    "zone",
    "release_speed",
    "effective_speed",
    "release_spin_rate",
    "release_extension",
    "release_pos_x",
    "release_pos_y",
    "release_pos_z",
    "pfx_x",
    "pfx_z",
    "plate_x",
    "plate_z",
    "sz_top",
    "sz_bot",
    "arm_angle",
    "events",
    "bb_type",
    "n_thruorder_pitcher",
    "launch_speed",
    "launch_angle",
    "hit_distance_sc",
    "estimated_ba_using_speedangle",
    "estimated_woba_using_speedangle",
    "woba_value",
    "delta_run_exp",
    "bat_speed",
    "swing_length",
    "home_score",
    "away_score",
    "bat_score",
    "fld_score",
]

INTEGER_COLUMNS = [
    "game_pk",
    "at_bat_number",
    "pitch_number",
    "pitcher",
    "batter",
    "balls",
    "strikes",
    "inning",
    "outs_when_up",
    "zone",
    "n_thruorder_pitcher",
    "home_score",
    "away_score",
    "bat_score",
    "fld_score",
]

FLOAT_COLUMNS = [
    "release_speed",
    "effective_speed",
    "release_spin_rate",
    "release_extension",
    "release_pos_x",
    "release_pos_y",
    "release_pos_z",
    "pfx_x",
    "pfx_z",
    "plate_x",
    "plate_z",
    "sz_top",
    "sz_bot",
    "arm_angle",
    "launch_speed",
    "launch_angle",
    "hit_distance_sc",
    "estimated_ba_using_speedangle",
    "estimated_woba_using_speedangle",
    "woba_value",
    "delta_run_exp",
    "bat_speed",
    "swing_length",
]

SWING_DESCRIPTIONS = {
    "swinging_strike",
    "swinging_strike_blocked",
    "missed_bunt",
    "foul",
    "foul_tip",
    "foul_bunt",
    "hit_into_play",
}
WHIFF_DESCRIPTIONS = {
    "swinging_strike",
    "swinging_strike_blocked",
    "missed_bunt",
}
CONTACT_DESCRIPTIONS = {
    "foul",
    "foul_tip",
    "foul_bunt",
    "hit_into_play",
}


class IngestionError(ValueError):
    """Raised when validation or the atomic database load fails."""


@dataclass(frozen=True)
class IngestionReport:
    ingestion_run_id: int
    source_rows: int
    inserted_rows: int
    updated_rows: int
    rejected_rows: int


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as source:
        for block in iter(lambda: source.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def _text(series: pd.Series, default: str = "") -> pd.Series:
    return series.astype("string").str.strip().fillna(default).replace("", default)


def _pitcher_names(series: pd.Series) -> pd.Series:
    """Convert Baseball Savant's ``Last, First`` names for display."""
    names = _text(series, "Unknown pitcher")

    def display_name(value: str) -> str:
        if "," not in value:
            return value
        last_name, first_name = value.split(",", 1)
        return f"{first_name.strip()} {last_name.strip()}".strip()

    return names.map(display_name)


def _optional_value(value: Any) -> Any:
    if pd.isna(value):
        return None
    return value.item() if hasattr(value, "item") else value


def _chunks(values: list[Any], size: int) -> Iterable[list[Any]]:
    for start in range(0, len(values), size):
        yield values[start : start + size]


def read_statcast_csv(path: Path) -> pd.DataFrame:
    """Read a CSV without hiding malformed input behind automatic defaults."""
    try:
        return pd.read_csv(path, low_memory=False)
    except (OSError, UnicodeError, pd.errors.ParserError) as exc:
        raise IngestionError(f"Could not read {path.name}: {exc}") from exc


def clean_statcast(raw: pd.DataFrame) -> pd.DataFrame:
    """Return one validated, analysis-ready record per Statcast pitch."""
    missing_columns = sorted(REQUIRED_COLUMNS - set(raw.columns))
    if missing_columns:
        raise IngestionError(
            "Statcast CSV is missing required columns: " + ", ".join(missing_columns)
        )
    if raw.empty:
        raise IngestionError("Statcast CSV contains no pitch rows.")

    data = raw.copy()
    for column in OPTIONAL_COLUMNS:
        if column not in data:
            data[column] = pd.NA

    required_non_null = [
        "game_date",
        "game_pk",
        "at_bat_number",
        "pitch_number",
        "pitch_type",
        "pitcher",
        "batter",
        "balls",
        "strikes",
        "description",
    ]
    invalid = data[required_non_null].isna().sum()
    invalid = invalid[invalid.gt(0)]
    if not invalid.empty:
        details = ", ".join(f"{column}={count}" for column, count in invalid.items())
        raise IngestionError(f"Required Statcast values are missing: {details}")

    for column in INTEGER_COLUMNS:
        numeric = pd.to_numeric(data[column], errors="coerce")
        present = data[column].notna()
        invalid_numeric = present & numeric.isna()
        if invalid_numeric.any():
            raise IngestionError(
                f"Column {column} contains {int(invalid_numeric.sum())} invalid integer value(s)."
            )
        non_integer = numeric.notna() & numeric.mod(1).ne(0)
        if non_integer.any():
            raise IngestionError(f"Column {column} contains non-integer values.")
        data[column] = numeric.astype("Int64")

    for column in FLOAT_COLUMNS:
        numeric = pd.to_numeric(data[column], errors="coerce")
        present = data[column].notna()
        invalid_numeric = present & numeric.isna()
        if invalid_numeric.any():
            raise IngestionError(
                f"Column {column} contains {int(invalid_numeric.sum())} invalid numeric value(s)."
            )
        data[column] = numeric

    if (~data["balls"].between(0, 3)).any():
        raise IngestionError("balls must be between 0 and 3.")
    if (~data["strikes"].between(0, 2)).any():
        raise IngestionError("strikes must be between 0 and 2.")

    parsed_dates = pd.to_datetime(data["game_date"], errors="coerce")
    if parsed_dates.isna().any():
        raise IngestionError(
            f"game_date contains {int(parsed_dates.isna().sum())} invalid date value(s)."
        )
    data["game_date"] = parsed_dates.dt.date
    data["season"] = parsed_dates.dt.year.astype(int)

    data["pitch_type"] = _text(data["pitch_type"]).str.upper()
    data["pitch_name"] = data["pitch_type"].map(PITCH_NAME_MAP).fillna(_text(data["pitch_name"]))
    data["player_name"] = _pitcher_names(data["player_name"])
    for column in [
        "game_type",
        "inning_topbot",
        "home_team",
        "away_team",
        "stand",
        "p_throws",
        "description",
        "events",
        "bb_type",
    ]:
        data[column] = _text(data[column])

    data["pitch_id"] = (
        data["game_pk"].astype("string")
        + "_"
        + data["at_bat_number"].astype("string")
        + "_"
        + data["pitch_number"].astype("string")
    )
    duplicates = data["pitch_id"].duplicated(keep=False)
    if duplicates.any():
        examples = ", ".join(data.loc[duplicates, "pitch_id"].drop_duplicates().head(10))
        raise IngestionError(f"Generated pitch_id values are not unique. Examples: {examples}")

    description = data["description"].str.lower()
    data["is_strike"] = data["type"].astype("string").str.upper().eq("S")
    data["is_swing"] = description.isin(SWING_DESCRIPTIONS)
    data["is_contact"] = description.isin(CONTACT_DESCRIPTIONS)
    data["is_whiff"] = description.isin(WHIFF_DESCRIPTIONS)
    data["is_csw"] = data["is_whiff"] | description.eq("called_strike")

    zone_known = data["zone"].notna()
    geometry_known = data[["plate_x", "plate_z", "sz_bot", "sz_top"]].notna().all(axis=1)
    in_zone_number = data["zone"].between(1, 9)
    in_zone_geometry = (
        data["plate_x"].between(-0.83, 0.83)
        & data["plate_z"].ge(data["sz_bot"])
        & data["plate_z"].le(data["sz_top"])
    )
    data["is_in_zone"] = in_zone_number.where(zone_known, in_zone_geometry).fillna(False)
    data["is_chase"] = data["is_swing"] & (zone_known | geometry_known) & ~data["is_in_zone"]
    data["is_hard_hit"] = data["launch_speed"].ge(95).fillna(False)
    return data


def _player_records(data: pd.DataFrame) -> list[dict[str, Any]]:
    players: dict[int, dict[str, Any]] = {}
    for row in data.itertuples(index=False):
        pitcher_id = int(row.pitcher)
        pitcher = players.setdefault(
            pitcher_id,
            {"mlb_id": pitcher_id, "player_name": None, "throws": None, "bats": None},
        )
        pitcher["player_name"] = str(row.player_name) or pitcher["player_name"]
        pitcher["throws"] = str(row.p_throws).upper() or pitcher["throws"]

        batter_id = int(row.batter)
        players.setdefault(
            batter_id,
            {"mlb_id": batter_id, "player_name": None, "throws": None, "bats": None},
        )
    return list(players.values())


def _game_records(data: pd.DataFrame) -> list[dict[str, Any]]:
    columns = ["game_pk", "game_date", "season", "game_type", "home_team", "away_team"]
    distinct = data[columns].drop_duplicates()
    conflicts = distinct["game_pk"].duplicated(keep=False)
    if conflicts.any():
        examples = ", ".join(distinct.loc[conflicts, "game_pk"].astype(str).unique()[:10])
        raise IngestionError(f"Conflicting game information for game_pk values: {examples}")

    return [
        {
            "game_pk": int(row.game_pk),
            "game_date": row.game_date,
            "season": int(row.season),
            "game_type": row.game_type or None,
            "home_team": str(row.home_team).upper(),
            "away_team": str(row.away_team).upper(),
        }
        for row in distinct.itertuples(index=False)
    ]


def _pitch_records(data: pd.DataFrame) -> list[dict[str, Any]]:
    mappings = {
        "pitch_id": "pitch_id",
        "game_pk": "game_pk",
        "pitcher_id": "pitcher",
        "batter_id": "batter",
        "at_bat_number": "at_bat_number",
        "pitch_number": "pitch_number",
        "inning": "inning",
        "inning_half": "inning_topbot",
        "outs_when_up": "outs_when_up",
        "batter_side": "stand",
        "pitch_type": "pitch_type",
        "pitch_name": "pitch_name",
        "balls": "balls",
        "strikes": "strikes",
        "zone": "zone",
        "velocity": "release_speed",
        "effective_velocity": "effective_speed",
        "spin_rate": "release_spin_rate",
        "release_extension": "release_extension",
        "release_pos_x": "release_pos_x",
        "release_pos_y": "release_pos_y",
        "release_pos_z": "release_pos_z",
        "plate_x": "plate_x",
        "plate_z": "plate_z",
        "strike_zone_top": "sz_top",
        "strike_zone_bottom": "sz_bot",
        "arm_angle": "arm_angle",
        "description": "description",
        "events": "events",
        "batted_ball_type": "bb_type",
        "is_strike": "is_strike",
        "is_swing": "is_swing",
        "is_contact": "is_contact",
        "is_whiff": "is_whiff",
        "is_csw": "is_csw",
        "is_in_zone": "is_in_zone",
        "is_chase": "is_chase",
        "is_hard_hit": "is_hard_hit",
        "times_through_order": "n_thruorder_pitcher",
        "exit_velocity": "launch_speed",
        "launch_angle": "launch_angle",
        "hit_distance": "hit_distance_sc",
        "estimated_ba": "estimated_ba_using_speedangle",
        "estimated_woba": "estimated_woba_using_speedangle",
        "woba_value": "woba_value",
        "delta_run_expectancy": "delta_run_exp",
        "bat_speed": "bat_speed",
        "swing_length": "swing_length",
        "home_score": "home_score",
        "away_score": "away_score",
        "batter_score": "bat_score",
        "fielding_score": "fld_score",
    }

    records: list[dict[str, Any]] = []
    for row in data.to_dict(orient="records"):
        record = {target: _optional_value(row[source]) for target, source in mappings.items()}
        record["game_pk"] = int(record["game_pk"])
        record["pitcher_id"] = int(record["pitcher_id"])
        record["batter_id"] = int(record["batter_id"])
        record["at_bat_number"] = int(record["at_bat_number"])
        record["pitch_number"] = int(record["pitch_number"])
        record["balls"] = int(record["balls"])
        record["strikes"] = int(record["strikes"])
        record["horizontal_break_inches"] = _optional_value(row["pfx_x"])
        record["vertical_break_inches"] = _optional_value(row["pfx_z"])
        if record["horizontal_break_inches"] is not None:
            record["horizontal_break_inches"] *= 12
        if record["vertical_break_inches"] is not None:
            record["vertical_break_inches"] *= 12
        records.append(record)
    return records


def _existing_pitch_ids(pitch_ids: list[str], batch_size: int) -> set[str]:
    existing: set[str] = set()
    for batch in _chunks(pitch_ids, batch_size):
        existing.update(db.session.scalars(select(Pitch.pitch_id).where(Pitch.pitch_id.in_(batch))))
    return existing


def _upsert(
    table,
    rows: list[dict[str, Any]],
    *,
    key_columns: list[str],
    update_columns: list[str],
    batch_size: int,
    preserve_existing_on_null: set[str] | None = None,
) -> None:
    if not rows:
        return

    dialect = db.session.get_bind().dialect.name
    if dialect == "postgresql":
        insert_factory = postgresql_insert
    elif dialect == "sqlite":
        insert_factory = sqlite_insert
    else:
        raise IngestionError(
            f"The ingestion command supports PostgreSQL and SQLite, not {dialect}."
        )

    base_statement = insert_factory(table)
    preserve_existing_on_null = preserve_existing_on_null or set()
    updates = {}
    for column in update_columns:
        excluded_value = getattr(base_statement.excluded, column)
        updates[column] = (
            func.coalesce(excluded_value, table.c[column])
            if column in preserve_existing_on_null
            else excluded_value
        )
    statement = base_statement.on_conflict_do_update(
        index_elements=[table.c[column] for column in key_columns],
        set_=updates,
    )

    for batch in _chunks(rows, batch_size):
        db.session.execute(statement, batch)


def ingest_statcast_file(path: Path, *, batch_size: int = 2_000) -> IngestionReport:
    """Audit and atomically upsert one Statcast file into the configured database."""
    source_path = path.expanduser().resolve()
    source_hash = _sha256(source_path)

    run = IngestionRun(
        source_file=source_path.name,
        source_sha256=source_hash,
        status="running",
    )
    db.session.add(run)
    db.session.commit()
    run_id = int(run.ingestion_run_id)

    source_rows = 0
    try:
        raw = read_statcast_csv(source_path)
        source_rows = len(raw)
        run.source_rows = source_rows
        db.session.commit()

        data = clean_statcast(raw)
        pitch_ids = data["pitch_id"].astype(str).tolist()
        existing = _existing_pitch_ids(pitch_ids, batch_size)

        player_rows = _player_records(data)
        game_rows = _game_records(data)
        pitch_rows = _pitch_records(data)

        _upsert(
            Player.__table__,
            player_rows,
            key_columns=["mlb_id"],
            update_columns=["player_name", "throws", "bats"],
            batch_size=batch_size,
            preserve_existing_on_null={"player_name", "throws", "bats"},
        )
        _upsert(
            Game.__table__,
            game_rows,
            key_columns=["game_pk"],
            update_columns=["game_date", "season", "game_type", "home_team", "away_team"],
            batch_size=batch_size,
        )
        _upsert(
            Pitch.__table__,
            pitch_rows,
            key_columns=["pitch_id"],
            update_columns=[
                column.name for column in Pitch.__table__.columns if not column.primary_key
            ],
            batch_size=batch_size,
        )

        inserted_rows = len(pitch_rows) - len(existing)
        updated_rows = len(existing)
        run.status = "succeeded"
        run.inserted_rows = inserted_rows
        run.updated_rows = updated_rows
        run.rejected_rows = 0
        run.finished_at = datetime.now(timezone.utc)
        db.session.commit()
    except Exception as exc:
        db.session.rollback()
        failed_run = db.session.get(IngestionRun, run_id)
        if failed_run is not None:
            failed_run.status = "failed"
            failed_run.source_rows = source_rows
            failed_run.rejected_rows = source_rows
            failed_run.error_message = str(exc)[:4_000]
            failed_run.finished_at = datetime.now(timezone.utc)
            db.session.commit()
        if isinstance(exc, IngestionError):
            raise
        raise IngestionError(f"Database load failed and was rolled back: {exc}") from exc

    return IngestionReport(
        ingestion_run_id=run_id,
        source_rows=source_rows,
        inserted_rows=inserted_rows,
        updated_rows=updated_rows,
        rejected_rows=0,
    )
