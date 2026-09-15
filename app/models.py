"""Relational models for MLB Statcast ingestion and later profile queries."""

from __future__ import annotations

from datetime import date, datetime, timezone

from sqlalchemy import CheckConstraint, Index, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.extensions import db


class Player(db.Model):
    __tablename__ = "players"

    mlb_id: Mapped[int] = mapped_column(primary_key=True)
    player_name: Mapped[str | None] = mapped_column(db.String(120), index=True)
    throws: Mapped[str | None] = mapped_column(db.String(1))
    bats: Mapped[str | None] = mapped_column(db.String(1))

    pitches_thrown: Mapped[list[Pitch]] = relationship(
        back_populates="pitcher",
        foreign_keys="Pitch.pitcher_id",
    )
    plate_appearances: Mapped[list[Pitch]] = relationship(
        back_populates="batter",
        foreign_keys="Pitch.batter_id",
    )


class Game(db.Model):
    __tablename__ = "games"

    game_pk: Mapped[int] = mapped_column(primary_key=True)
    game_date: Mapped[date] = mapped_column(db.Date, nullable=False, index=True)
    season: Mapped[int] = mapped_column(db.SmallInteger, nullable=False, index=True)
    game_type: Mapped[str | None] = mapped_column(db.String(2))
    home_team: Mapped[str] = mapped_column(db.String(5), nullable=False)
    away_team: Mapped[str] = mapped_column(db.String(5), nullable=False)

    pitches: Mapped[list[Pitch]] = relationship(back_populates="game")


class Pitch(db.Model):
    __tablename__ = "pitches"
    __table_args__ = (
        UniqueConstraint(
            "game_pk",
            "at_bat_number",
            "pitch_number",
            name="uq_pitches_pitch_natural_key",
        ),
        CheckConstraint("balls BETWEEN 0 AND 3", name="valid_balls"),
        CheckConstraint("strikes BETWEEN 0 AND 2", name="valid_strikes"),
        Index(
            "ix_pitches_pitcher_game_order",
            "pitcher_id",
            "game_pk",
            "at_bat_number",
            "pitch_number",
        ),
        Index("ix_pitches_profile_filters", "pitcher_id", "pitch_type", "batter_side"),
        Index("ix_pitches_count", "pitcher_id", "balls", "strikes"),
    )

    pitch_id: Mapped[str] = mapped_column(db.String(100), primary_key=True)
    game_pk: Mapped[int] = mapped_column(db.ForeignKey("games.game_pk"), nullable=False)
    pitcher_id: Mapped[int] = mapped_column(db.ForeignKey("players.mlb_id"), nullable=False)
    batter_id: Mapped[int] = mapped_column(db.ForeignKey("players.mlb_id"), nullable=False)
    at_bat_number: Mapped[int] = mapped_column(nullable=False)
    pitch_number: Mapped[int] = mapped_column(nullable=False)
    inning: Mapped[int | None]
    inning_half: Mapped[str | None] = mapped_column(db.String(10))
    outs_when_up: Mapped[int | None] = mapped_column(db.SmallInteger)
    batter_side: Mapped[str | None] = mapped_column(db.String(1))
    pitch_type: Mapped[str] = mapped_column(db.String(4), nullable=False)
    pitch_name: Mapped[str | None] = mapped_column(db.String(50))
    balls: Mapped[int] = mapped_column(db.SmallInteger, nullable=False)
    strikes: Mapped[int] = mapped_column(db.SmallInteger, nullable=False)
    zone: Mapped[int | None] = mapped_column(db.SmallInteger)
    velocity: Mapped[float | None]
    effective_velocity: Mapped[float | None]
    spin_rate: Mapped[float | None]
    horizontal_break_inches: Mapped[float | None]
    vertical_break_inches: Mapped[float | None]
    release_extension: Mapped[float | None]
    release_pos_x: Mapped[float | None]
    release_pos_y: Mapped[float | None]
    release_pos_z: Mapped[float | None]
    plate_x: Mapped[float | None]
    plate_z: Mapped[float | None]
    strike_zone_top: Mapped[float | None]
    strike_zone_bottom: Mapped[float | None]
    arm_angle: Mapped[float | None]
    description: Mapped[str | None] = mapped_column(db.String(50))
    events: Mapped[str | None] = mapped_column(db.String(50))
    batted_ball_type: Mapped[str | None] = mapped_column(db.String(30))
    is_strike: Mapped[bool] = mapped_column(default=False, nullable=False)
    is_swing: Mapped[bool] = mapped_column(default=False, nullable=False)
    is_contact: Mapped[bool] = mapped_column(default=False, nullable=False)
    is_whiff: Mapped[bool] = mapped_column(default=False, nullable=False)
    is_csw: Mapped[bool] = mapped_column(default=False, nullable=False)
    is_in_zone: Mapped[bool] = mapped_column(default=False, nullable=False)
    is_chase: Mapped[bool] = mapped_column(default=False, nullable=False)
    is_hard_hit: Mapped[bool] = mapped_column(default=False, nullable=False)
    times_through_order: Mapped[int | None] = mapped_column(db.SmallInteger)
    exit_velocity: Mapped[float | None]
    launch_angle: Mapped[float | None]
    hit_distance: Mapped[float | None]
    estimated_ba: Mapped[float | None]
    estimated_woba: Mapped[float | None]
    woba_value: Mapped[float | None]
    delta_run_expectancy: Mapped[float | None]
    bat_speed: Mapped[float | None]
    swing_length: Mapped[float | None]
    home_score: Mapped[int | None] = mapped_column(db.SmallInteger)
    away_score: Mapped[int | None] = mapped_column(db.SmallInteger)
    batter_score: Mapped[int | None] = mapped_column(db.SmallInteger)
    fielding_score: Mapped[int | None] = mapped_column(db.SmallInteger)

    game: Mapped[Game] = relationship(back_populates="pitches")
    pitcher: Mapped[Player] = relationship(
        back_populates="pitches_thrown",
        foreign_keys=[pitcher_id],
    )
    batter: Mapped[Player] = relationship(
        back_populates="plate_appearances",
        foreign_keys=[batter_id],
    )


class IngestionRun(db.Model):
    __tablename__ = "ingestion_runs"

    ingestion_run_id: Mapped[int] = mapped_column(primary_key=True)
    source_file: Mapped[str] = mapped_column(db.String(500), nullable=False)
    source_sha256: Mapped[str] = mapped_column(db.String(64), nullable=False, index=True)
    status: Mapped[str] = mapped_column(db.String(20), nullable=False, index=True)
    source_rows: Mapped[int] = mapped_column(default=0, nullable=False)
    inserted_rows: Mapped[int] = mapped_column(default=0, nullable=False)
    updated_rows: Mapped[int] = mapped_column(default=0, nullable=False)
    rejected_rows: Mapped[int] = mapped_column(default=0, nullable=False)
    error_message: Mapped[str | None] = mapped_column(db.Text)
    started_at: Mapped[datetime] = mapped_column(
        db.DateTime(timezone=True),
        default=lambda: datetime.now(timezone.utc),
        nullable=False,
    )
    finished_at: Mapped[datetime | None] = mapped_column(db.DateTime(timezone=True))
