"""Create the initial Statcast ingestion schema.

Revision ID: 0001_statcast_schema
Revises: None
"""

import sqlalchemy as sa
from alembic import op

revision = "0001_statcast_schema"
down_revision = None
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "players",
        sa.Column("mlb_id", sa.Integer(), nullable=False),
        sa.Column("player_name", sa.String(length=120), nullable=True),
        sa.Column("throws", sa.String(length=1), nullable=True),
        sa.Column("bats", sa.String(length=1), nullable=True),
        sa.PrimaryKeyConstraint("mlb_id", name="pk_players"),
    )
    op.create_index("ix_players_player_name", "players", ["player_name"])

    op.create_table(
        "games",
        sa.Column("game_pk", sa.Integer(), nullable=False),
        sa.Column("game_date", sa.Date(), nullable=False),
        sa.Column("season", sa.SmallInteger(), nullable=False),
        sa.Column("game_type", sa.String(length=2), nullable=True),
        sa.Column("home_team", sa.String(length=5), nullable=False),
        sa.Column("away_team", sa.String(length=5), nullable=False),
        sa.PrimaryKeyConstraint("game_pk", name="pk_games"),
    )
    op.create_index("ix_games_game_date", "games", ["game_date"])
    op.create_index("ix_games_season", "games", ["season"])

    op.create_table(
        "ingestion_runs",
        sa.Column("ingestion_run_id", sa.Integer(), nullable=False),
        sa.Column("source_file", sa.String(length=500), nullable=False),
        sa.Column("source_sha256", sa.String(length=64), nullable=False),
        sa.Column("status", sa.String(length=20), nullable=False),
        sa.Column("source_rows", sa.Integer(), nullable=False),
        sa.Column("inserted_rows", sa.Integer(), nullable=False),
        sa.Column("updated_rows", sa.Integer(), nullable=False),
        sa.Column("rejected_rows", sa.Integer(), nullable=False),
        sa.Column("error_message", sa.Text(), nullable=True),
        sa.Column("started_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("finished_at", sa.DateTime(timezone=True), nullable=True),
        sa.PrimaryKeyConstraint("ingestion_run_id", name="pk_ingestion_runs"),
    )
    op.create_index("ix_ingestion_runs_source_sha256", "ingestion_runs", ["source_sha256"])
    op.create_index("ix_ingestion_runs_status", "ingestion_runs", ["status"])

    op.create_table(
        "pitches",
        sa.Column("pitch_id", sa.String(length=100), nullable=False),
        sa.Column("game_pk", sa.Integer(), nullable=False),
        sa.Column("pitcher_id", sa.Integer(), nullable=False),
        sa.Column("batter_id", sa.Integer(), nullable=False),
        sa.Column("at_bat_number", sa.Integer(), nullable=False),
        sa.Column("pitch_number", sa.Integer(), nullable=False),
        sa.Column("inning", sa.Integer(), nullable=True),
        sa.Column("inning_half", sa.String(length=10), nullable=True),
        sa.Column("outs_when_up", sa.SmallInteger(), nullable=True),
        sa.Column("batter_side", sa.String(length=1), nullable=True),
        sa.Column("pitch_type", sa.String(length=4), nullable=False),
        sa.Column("pitch_name", sa.String(length=50), nullable=True),
        sa.Column("balls", sa.SmallInteger(), nullable=False),
        sa.Column("strikes", sa.SmallInteger(), nullable=False),
        sa.Column("zone", sa.SmallInteger(), nullable=True),
        sa.Column("velocity", sa.Float(), nullable=True),
        sa.Column("effective_velocity", sa.Float(), nullable=True),
        sa.Column("spin_rate", sa.Float(), nullable=True),
        sa.Column("horizontal_break_inches", sa.Float(), nullable=True),
        sa.Column("vertical_break_inches", sa.Float(), nullable=True),
        sa.Column("release_extension", sa.Float(), nullable=True),
        sa.Column("release_pos_x", sa.Float(), nullable=True),
        sa.Column("release_pos_y", sa.Float(), nullable=True),
        sa.Column("release_pos_z", sa.Float(), nullable=True),
        sa.Column("plate_x", sa.Float(), nullable=True),
        sa.Column("plate_z", sa.Float(), nullable=True),
        sa.Column("strike_zone_top", sa.Float(), nullable=True),
        sa.Column("strike_zone_bottom", sa.Float(), nullable=True),
        sa.Column("arm_angle", sa.Float(), nullable=True),
        sa.Column("description", sa.String(length=50), nullable=True),
        sa.Column("events", sa.String(length=50), nullable=True),
        sa.Column("batted_ball_type", sa.String(length=30), nullable=True),
        sa.Column("is_strike", sa.Boolean(), nullable=False),
        sa.Column("is_swing", sa.Boolean(), nullable=False),
        sa.Column("is_contact", sa.Boolean(), nullable=False),
        sa.Column("is_whiff", sa.Boolean(), nullable=False),
        sa.Column("is_csw", sa.Boolean(), nullable=False),
        sa.Column("is_in_zone", sa.Boolean(), nullable=False),
        sa.Column("is_chase", sa.Boolean(), nullable=False),
        sa.Column("is_hard_hit", sa.Boolean(), nullable=False),
        sa.Column("times_through_order", sa.SmallInteger(), nullable=True),
        sa.Column("exit_velocity", sa.Float(), nullable=True),
        sa.Column("launch_angle", sa.Float(), nullable=True),
        sa.Column("hit_distance", sa.Float(), nullable=True),
        sa.Column("estimated_ba", sa.Float(), nullable=True),
        sa.Column("estimated_woba", sa.Float(), nullable=True),
        sa.Column("woba_value", sa.Float(), nullable=True),
        sa.Column("delta_run_expectancy", sa.Float(), nullable=True),
        sa.Column("bat_speed", sa.Float(), nullable=True),
        sa.Column("swing_length", sa.Float(), nullable=True),
        sa.Column("home_score", sa.SmallInteger(), nullable=True),
        sa.Column("away_score", sa.SmallInteger(), nullable=True),
        sa.Column("batter_score", sa.SmallInteger(), nullable=True),
        sa.Column("fielding_score", sa.SmallInteger(), nullable=True),
        sa.CheckConstraint("balls BETWEEN 0 AND 3", name="ck_pitches_valid_balls"),
        sa.CheckConstraint("strikes BETWEEN 0 AND 2", name="ck_pitches_valid_strikes"),
        sa.ForeignKeyConstraint(
            ["batter_id"],
            ["players.mlb_id"],
            name="fk_pitches_batter_id_players",
        ),
        sa.ForeignKeyConstraint(["game_pk"], ["games.game_pk"], name="fk_pitches_game_pk_games"),
        sa.ForeignKeyConstraint(
            ["pitcher_id"],
            ["players.mlb_id"],
            name="fk_pitches_pitcher_id_players",
        ),
        sa.PrimaryKeyConstraint("pitch_id", name="pk_pitches"),
        sa.UniqueConstraint(
            "game_pk",
            "at_bat_number",
            "pitch_number",
            name="uq_pitches_pitch_natural_key",
        ),
    )
    op.create_index(
        "ix_pitches_pitcher_game_order",
        "pitches",
        ["pitcher_id", "game_pk", "at_bat_number", "pitch_number"],
    )
    op.create_index(
        "ix_pitches_profile_filters",
        "pitches",
        ["pitcher_id", "pitch_type", "batter_side"],
    )
    op.create_index("ix_pitches_count", "pitches", ["pitcher_id", "balls", "strikes"])


def downgrade() -> None:
    op.drop_index("ix_pitches_count", table_name="pitches")
    op.drop_index("ix_pitches_profile_filters", table_name="pitches")
    op.drop_index("ix_pitches_pitcher_game_order", table_name="pitches")
    op.drop_table("pitches")
    op.drop_index("ix_ingestion_runs_status", table_name="ingestion_runs")
    op.drop_index("ix_ingestion_runs_source_sha256", table_name="ingestion_runs")
    op.drop_table("ingestion_runs")
    op.drop_index("ix_games_season", table_name="games")
    op.drop_index("ix_games_game_date", table_name="games")
    op.drop_table("games")
    op.drop_index("ix_players_player_name", table_name="players")
    op.drop_table("players")
