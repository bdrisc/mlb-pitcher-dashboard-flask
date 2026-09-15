"""Load and query pitch data through one canonical in-memory schema."""

from __future__ import annotations

from datetime import date, datetime, timezone
from pathlib import Path

import pandas as pd

PITCH_NAME_MAP = {
    "FF": "Four-Seam Fastball",
    "FA": "Fastball",
    "SI": "Sinker",
    "FC": "Cutter",
    "CH": "Changeup",
    "FS": "Split-Finger",
    "FO": "Forkball",
    "SC": "Screwball",
    "SL": "Slider",
    "ST": "Sweeper",
    "SV": "Slurve",
    "CU": "Curveball",
    "KC": "Knuckle Curve",
    "CS": "Slow Curve",
    "KN": "Knuckleball",
    "EP": "Eephus",
}

TRACKMAN_NAME_MAP = {
    "FourSeamFastBall": "Four-Seam Fastball",
    "Four-Seam": "Four-Seam Fastball",
    "Fastball": "Four-Seam Fastball",
    "2-Seam": "Two-Seam Fastball",
    "TwoSeamFastBall": "Two-Seam Fastball",
    "Sinker": "Sinker",
    "ChangeUp": "Changeup",
    "Slider": "Slider",
    "Curveball": "Curveball",
    "Cutter": "Cutter",
    "Splitter": "Split-Finger",
}

CANONICAL_COLUMNS = [
    "pitcher",
    "team",
    "game_date",
    "season",
    "home_away",
    "balls",
    "strikes",
    "pitch_type_code",
    "pitch_type",
    "velocity",
    "spin_rate",
    "horizontal_break",
    "vertical_break",
    "batter_side",
    "pitcher_throws",
]


class PitchDataStore:
    """Own the loaded DataFrame and keep data work out of Flask routes."""

    def __init__(self, path: str | Path):
        self.path = Path(path).expanduser()
        self.data = pd.DataFrame(columns=CANONICAL_COLUMNS)
        self.error: str | None = None
        self.loaded_at: datetime | None = None
        self.source_format: str | None = None

    @property
    def available(self) -> bool:
        return self.error is None and not self.data.empty

    @property
    def status(self) -> str:
        return "ok" if self.available else "unavailable"

    @property
    def row_count(self) -> int:
        return int(len(self.data))

    @property
    def source_name(self) -> str:
        return self.path.name

    def load(self) -> None:
        """Read and normalize the configured source without crashing startup."""
        self.error = None
        try:
            if not self.path.is_file():
                raise FileNotFoundError(f"Pitch data file not found: {self.path}")
            raw = pd.read_csv(self.path, low_memory=False)
            self.data, self.source_format = self._normalize(raw)
            if self.data.empty:
                raise ValueError("The configured pitch data file contains no rows.")
            self.loaded_at = datetime.now(timezone.utc)
        except (OSError, ValueError, pd.errors.ParserError) as exc:
            self.data = pd.DataFrame(columns=CANONICAL_COLUMNS)
            self.error = str(exc)
            self.loaded_at = None
            self.source_format = None

    def _normalize(self, raw: pd.DataFrame) -> tuple[pd.DataFrame, str]:
        if {"player_name", "pitch_type", "release_speed", "pfx_x", "pfx_z"}.issubset(raw.columns):
            return self._normalize_statcast(raw), "MLB Statcast"
        if {
            "Pitcher",
            "TaggedPitchType",
            "RelSpeed",
            "HorzBreak",
            "InducedVertBreak",
        }.issubset(raw.columns):
            return self._normalize_trackman(raw), "TrackMan"
        raise ValueError(
            "Unsupported pitch-data schema. Expected MLB Statcast columns "
            "(player_name, pitch_type, release_speed, pfx_x, pfx_z) or the "
            "legacy TrackMan columns used by the original script."
        )

    @staticmethod
    def _numeric(frame: pd.DataFrame, column: str) -> pd.Series:
        if column not in frame:
            return pd.Series(float("nan"), index=frame.index, dtype="float64")
        return pd.to_numeric(frame[column], errors="coerce")

    def _normalize_statcast(self, raw: pd.DataFrame) -> pd.DataFrame:
        pitch_codes = raw["pitch_type"].astype("string").str.strip().str.upper()
        pitch_names = pitch_codes.map(PITCH_NAME_MAP).fillna(pitch_codes)

        game_dates = pd.to_datetime(
            raw.get("game_date", pd.Series(pd.NaT, index=raw.index)), errors="coerce"
        )
        seasons = self._numeric(raw, "game_year")
        seasons = seasons.where(seasons.notna(), game_dates.dt.year)

        team = pd.Series("", index=raw.index, dtype="string")
        home_away = pd.Series("", index=raw.index, dtype="string")
        if {"inning_topbot", "home_team", "away_team"}.issubset(raw.columns):
            inning_half = raw["inning_topbot"].astype("string").str.strip().str.lower()
            is_top = inning_half.eq("top")
            is_bottom = inning_half.isin({"bot", "bottom"})
            team = team.mask(is_top, raw["home_team"].astype("string"))
            team = team.mask(is_bottom, raw["away_team"].astype("string"))
            home_away = home_away.mask(is_top, "home").mask(is_bottom, "away")

        normalized = pd.DataFrame(
            {
                "pitcher": raw["player_name"].astype("string").str.strip(),
                "team": team.str.strip().str.upper(),
                "game_date": game_dates.dt.date,
                "season": seasons.astype("Int64"),
                "home_away": home_away,
                "balls": self._numeric(raw, "balls").astype("Int64"),
                "strikes": self._numeric(raw, "strikes").astype("Int64"),
                "pitch_type_code": pitch_codes,
                "pitch_type": pitch_names,
                "velocity": self._numeric(raw, "release_speed"),
                "spin_rate": self._numeric(raw, "release_spin_rate"),
                # Statcast pfx values are feet; the app's display unit is inches.
                "horizontal_break": self._numeric(raw, "pfx_x") * 12,
                "vertical_break": self._numeric(raw, "pfx_z") * 12,
                "batter_side": raw.get("stand", pd.Series("", index=raw.index))
                .astype("string")
                .str.strip()
                .str.upper(),
                "pitcher_throws": raw.get("p_throws", pd.Series("", index=raw.index))
                .astype("string")
                .str.strip()
                .str.upper(),
            }
        )
        return normalized

    def _normalize_trackman(self, raw: pd.DataFrame) -> pd.DataFrame:
        tagged = raw["TaggedPitchType"].astype("string").str.strip()
        pitch_names = tagged.map(TRACKMAN_NAME_MAP).fillna(tagged)
        game_dates = pd.to_datetime(
            raw.get("Date", pd.Series(pd.NaT, index=raw.index)), errors="coerce"
        )
        return pd.DataFrame(
            {
                "pitcher": raw["Pitcher"].astype("string").str.strip(),
                "team": raw.get("PitcherTeam", pd.Series("", index=raw.index))
                .astype("string")
                .str.strip(),
                "game_date": game_dates.dt.date,
                "season": game_dates.dt.year.astype("Int64"),
                "home_away": pd.Series("", index=raw.index, dtype="string"),
                "balls": self._numeric(raw, "Balls").astype("Int64"),
                "strikes": self._numeric(raw, "Strikes").astype("Int64"),
                "pitch_type_code": tagged,
                "pitch_type": pitch_names,
                "velocity": self._numeric(raw, "RelSpeed"),
                "spin_rate": self._numeric(raw, "SpinRate"),
                "horizontal_break": self._numeric(raw, "HorzBreak"),
                "vertical_break": self._numeric(raw, "InducedVertBreak"),
                "batter_side": raw.get("BatterSide", pd.Series("", index=raw.index))
                .astype("string")
                .str.strip(),
                "pitcher_throws": raw.get("PitcherThrows", pd.Series("", index=raw.index))
                .astype("string")
                .str.strip(),
            }
        )

    def filter(
        self,
        *,
        pitcher: str | None = None,
        team: str | None = None,
        pitch_types: tuple[str, ...] = (),
        batter_sides: tuple[str, ...] = (),
        season: int | None = None,
        date_from: date | None = None,
        date_to: date | None = None,
        balls: int | None = None,
        strikes: int | None = None,
        home_away: str | None = None,
    ) -> pd.DataFrame:
        filtered = self.data
        if pitcher:
            filtered = filtered[
                filtered["pitcher"].str.contains(pitcher, case=False, na=False, regex=False)
            ]
        if team:
            filtered = filtered[filtered["team"].str.upper().eq(team)]
        if pitch_types:
            filtered = filtered[filtered["pitch_type_code"].isin(pitch_types)]
        if batter_sides:
            filtered = filtered[filtered["batter_side"].isin(batter_sides)]
        if season is not None:
            filtered = filtered[filtered["season"].eq(season)]
        if date_from is not None:
            filtered = filtered[filtered["game_date"].ge(date_from)]
        if date_to is not None:
            filtered = filtered[filtered["game_date"].le(date_to)]
        if balls is not None:
            filtered = filtered[filtered["balls"].eq(balls)]
        if strikes is not None:
            filtered = filtered[filtered["strikes"].eq(strikes)]
        if home_away:
            filtered = filtered[filtered["home_away"].eq(home_away)]

        return filtered.copy()

    def pitcher_options(self) -> list[dict]:
        grouped = (
            self.data.groupby(["pitcher", "team"], dropna=False)
            .size()
            .rename("pitch_count")
            .reset_index()
            .sort_values(["pitcher", "team"])
        )
        return self._records(grouped)

    def summarize(self, frame: pd.DataFrame) -> list[dict]:
        summary = (
            frame.groupby("pitch_type", dropna=False)
            .agg(
                pitch_count=("pitch_type", "size"),
                avg_velocity=("velocity", "mean"),
                max_velocity=("velocity", "max"),
                avg_spin=("spin_rate", "mean"),
                horizontal_break=("horizontal_break", "mean"),
                vertical_break=("vertical_break", "mean"),
            )
            .reset_index()
            .sort_values(["pitch_count", "pitch_type"], ascending=[False, True])
        )
        numeric_columns = [
            "avg_velocity",
            "max_velocity",
            "avg_spin",
            "horizontal_break",
            "vertical_break",
        ]
        summary[numeric_columns] = summary[numeric_columns].round(1)
        return self._records(summary)

    @staticmethod
    def _records(frame: pd.DataFrame) -> list[dict]:
        cleaned = frame.astype(object).where(pd.notna(frame), None)
        return cleaned.to_dict(orient="records")
