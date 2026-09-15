"""Download resumable Statcast chunks and build a production-sized sample."""

from __future__ import annotations

import json
import time
import warnings
from collections import Counter
from collections.abc import Callable
from dataclasses import dataclass
from datetime import date, datetime, timedelta, timezone
from pathlib import Path

import pandas as pd

from app.services.statcast_ingestion import REQUIRED_COLUMNS

REGULAR_SEASON_GAME_TYPE = "R"
STATCAST_FIRST_SEASON = 2015


class StatcastAcquisitionError(RuntimeError):
    """Raised when Statcast data cannot be downloaded or exported safely."""


@dataclass(frozen=True)
class DateChunk:
    start_date: date
    end_date: date


@dataclass(frozen=True)
class CachedStatcastChunk:
    start_date: date
    end_date: date
    path: Path
    source_rows: int
    pitch_rows: int
    dropped_rows: int
    from_cache: bool


@dataclass(frozen=True)
class ProductionSampleReport:
    output_path: Path
    manifest_path: Path
    pitcher_count: int
    pitch_count: int


def season_date_range(
    season: int,
    *,
    through: date | None = None,
    today: date | None = None,
) -> tuple[date, date]:
    """Return broad Statcast bounds for one regular season.

    The regular-season filter is applied after download, so broad March-November
    bounds remain correct when MLB changes the exact schedule dates.
    """
    if season < STATCAST_FIRST_SEASON:
        raise StatcastAcquisitionError(
            f"Season must be {STATCAST_FIRST_SEASON} or later for this project."
        )

    current_date = today or date.today()
    start_date = date(season, 3, 15)
    last_possible_date = date(season, 11, 15)

    if through is not None:
        if through.year != season:
            raise StatcastAcquisitionError("--through must fall within the selected season.")
        end_date = min(through, last_possible_date)
    elif season < current_date.year:
        end_date = last_possible_date
    elif season == current_date.year:
        end_date = min(current_date - timedelta(days=1), last_possible_date)
    else:
        raise StatcastAcquisitionError("Cannot download a future Statcast season.")

    if end_date < start_date:
        raise StatcastAcquisitionError("No Statcast dates are available for that range yet.")
    return start_date, end_date


def iter_date_chunks(start_date: date, end_date: date, chunk_days: int) -> list[DateChunk]:
    """Split an inclusive date range into deterministic, non-overlapping chunks."""
    if chunk_days < 1:
        raise ValueError("chunk_days must be at least 1.")
    if end_date < start_date:
        raise ValueError("end_date must be on or after start_date.")

    chunks: list[DateChunk] = []
    cursor = start_date
    while cursor <= end_date:
        chunk_end = min(cursor + timedelta(days=chunk_days - 1), end_date)
        chunks.append(DateChunk(cursor, chunk_end))
        cursor = chunk_end + timedelta(days=1)
    return chunks


def _fetch_with_pybaseball(start_date: date, end_date: date) -> pd.DataFrame:
    try:
        from pybaseball import statcast
    except ImportError as exc:
        raise StatcastAcquisitionError(
            "Season downloads require pybaseball. Install requirements-data.txt first."
        ) from exc

    with warnings.catch_warnings():
        warnings.filterwarnings(
            "ignore",
            category=FutureWarning,
            module=r"pybaseball(\..*)?",
        )
        return statcast(
            start_dt=start_date.isoformat(),
            end_dt=end_date.isoformat(),
            verbose=False,
            parallel=False,
        )


def _prepare_download(frame: pd.DataFrame) -> tuple[pd.DataFrame, int]:
    """Keep valid regular-season pitches that the strict loader can ingest."""
    if frame.empty:
        columns = list(frame.columns) or sorted(REQUIRED_COLUMNS | {"game_type"})
        return pd.DataFrame(columns=columns), 0

    missing = sorted(REQUIRED_COLUMNS - set(frame.columns))
    if missing:
        raise StatcastAcquisitionError(
            "Downloaded Statcast data are missing required columns: " + ", ".join(missing)
        )

    data = frame.copy()
    if "game_type" in data:
        data = data.loc[data["game_type"].astype("string").eq(REGULAR_SEASON_GAME_TYPE)]

    required = sorted(REQUIRED_COLUMNS)
    valid = data[required].notna().all(axis=1)
    prepared = data.loc[valid].copy()
    prepared = prepared.drop_duplicates(
        subset=["game_pk", "at_bat_number", "pitch_number"],
        keep="last",
    )
    dropped_rows = len(frame) - len(prepared)
    return prepared, dropped_rows


def _chunk_path(cache_dir: Path, chunk: DateChunk) -> Path:
    return cache_dir / (
        f"statcast_{chunk.start_date.isoformat()}_{chunk.end_date.isoformat()}.csv.gz"
    )


def acquire_statcast_chunk(
    chunk: DateChunk,
    *,
    cache_dir: Path,
    retries: int = 3,
    retry_delay_seconds: float = 2.0,
    force_download: bool = False,
    fetcher: Callable[[date, date], pd.DataFrame] | None = None,
) -> CachedStatcastChunk:
    """Download and cache one validated interval, or reuse its existing cache."""
    cache_dir = cache_dir.expanduser().resolve()
    cache_dir.mkdir(parents=True, exist_ok=True)
    destination = _chunk_path(cache_dir, chunk)

    if destination.exists() and not force_download:
        cached = pd.read_csv(destination, low_memory=False)
        return CachedStatcastChunk(
            start_date=chunk.start_date,
            end_date=chunk.end_date,
            path=destination,
            source_rows=len(cached),
            pitch_rows=len(cached),
            dropped_rows=0,
            from_cache=True,
        )

    active_fetcher = fetcher or _fetch_with_pybaseball
    last_error: Exception | None = None
    for attempt in range(1, retries + 1):
        try:
            downloaded = active_fetcher(chunk.start_date, chunk.end_date)
            prepared, dropped_rows = _prepare_download(downloaded)
            temporary = destination.with_name(destination.name + ".tmp")
            prepared.to_csv(temporary, index=False, compression="gzip")
            temporary.replace(destination)
            return CachedStatcastChunk(
                start_date=chunk.start_date,
                end_date=chunk.end_date,
                path=destination,
                source_rows=len(downloaded),
                pitch_rows=len(prepared),
                dropped_rows=dropped_rows,
                from_cache=False,
            )
        except StatcastAcquisitionError:
            raise
        except Exception as exc:  # pragma: no cover - exact network errors vary by platform
            last_error = exc
            if attempt < retries:
                time.sleep(retry_delay_seconds * attempt)

    raise StatcastAcquisitionError(
        f"Could not download {chunk.start_date} through {chunk.end_date} "
        f"after {retries} attempt(s): {last_error}"
    )


def _display_name(value: object) -> str:
    name = str(value).strip()
    if "," not in name:
        return name
    last_name, first_name = name.split(",", 1)
    return f"{first_name.strip()} {last_name.strip()}".strip()


def build_top_pitcher_sample(
    *,
    season: int,
    cache_dir: Path,
    output_path: Path,
    pitcher_limit: int = 50,
) -> ProductionSampleReport:
    """Export complete cached histories for the busiest pitchers in a season."""
    if pitcher_limit < 1:
        raise StatcastAcquisitionError("pitcher_limit must be at least 1.")

    cache_dir = cache_dir.expanduser().resolve()
    files = sorted(cache_dir.glob(f"statcast_{season}-*.csv.gz"))
    if not files:
        raise StatcastAcquisitionError(
            f"No cached {season} Statcast chunks were found in {cache_dir}."
        )

    identity_frames: list[pd.DataFrame] = []
    for source in files:
        identity_frames.append(
            pd.read_csv(
                source,
                usecols=[
                    "game_pk",
                    "at_bat_number",
                    "pitch_number",
                    "pitcher",
                    "player_name",
                ],
                low_memory=False,
            )
        )

    identities = pd.concat(identity_frames, ignore_index=True).drop_duplicates(
        subset=["game_pk", "at_bat_number", "pitch_number"],
        keep="last",
    )
    identities["pitcher"] = pd.to_numeric(identities["pitcher"], errors="coerce")
    identities = identities.dropna(subset=["pitcher"])
    identities["pitcher"] = identities["pitcher"].astype(int)
    counts = Counter(identities["pitcher"].tolist())
    names = {
        int(row.pitcher): _display_name(row.player_name)
        for row in identities[["pitcher", "player_name"]]
        .dropna(subset=["player_name"])
        .drop_duplicates(subset=["pitcher"], keep="last")
        .itertuples(index=False)
    }

    ranked_pitchers = sorted(counts, key=lambda pitcher_id: (-counts[pitcher_id], pitcher_id))[
        :pitcher_limit
    ]
    selected_ids = set(ranked_pitchers)
    selected_frames: list[pd.DataFrame] = []
    for source in files:
        frame = pd.read_csv(source, low_memory=False)
        pitcher_ids = pd.to_numeric(frame["pitcher"], errors="coerce")
        selected = frame.loc[pitcher_ids.isin(selected_ids)]
        if not selected.empty:
            selected_frames.append(selected)

    if not selected_frames:
        raise StatcastAcquisitionError("No pitches matched the selected pitchers.")

    sample = pd.concat(selected_frames, ignore_index=True)
    sample = sample.drop_duplicates(
        subset=["game_pk", "at_bat_number", "pitch_number"],
        keep="last",
    ).sort_values(["game_date", "game_pk", "at_bat_number", "pitch_number"])

    output_path = output_path.expanduser().resolve()
    output_path.parent.mkdir(parents=True, exist_ok=True)
    temporary = output_path.with_name(output_path.name + ".tmp")
    sample.to_csv(temporary, index=False, compression="gzip")
    temporary.replace(output_path)

    output_stem = str(output_path)
    if output_stem.endswith(".csv.gz"):
        output_stem = output_stem[: -len(".csv.gz")]
    manifest_path = Path(output_stem + ".manifest.json")
    manifest = {
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "season": season,
        "selection_rule": f"top {pitcher_limit} pitchers by total cached pitch count",
        "pitcher_count": len(ranked_pitchers),
        "pitch_count": len(sample),
        "pitchers": [
            {
                "mlb_id": pitcher_id,
                "name": names.get(pitcher_id, "Unknown pitcher"),
                "pitch_count": counts[pitcher_id],
            }
            for pitcher_id in ranked_pitchers
        ],
    }
    manifest_path.write_text(json.dumps(manifest, indent=2) + "\n", encoding="utf-8")

    return ProductionSampleReport(
        output_path=output_path,
        manifest_path=manifest_path,
        pitcher_count=len(ranked_pitchers),
        pitch_count=len(sample),
    )
