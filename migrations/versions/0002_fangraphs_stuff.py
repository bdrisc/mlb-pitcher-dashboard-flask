"""Store season-level FanGraphs Stuff+ grades."""

import sqlalchemy as sa
from alembic import op

revision = "0002_fangraphs_stuff"
down_revision = "0001_statcast_schema"
branch_labels = None
depends_on = None


def upgrade():
    op.create_table(
        "fangraphs_stuff",
        sa.Column("mlb_id", sa.Integer(), primary_key=True),
        sa.Column("season", sa.SmallInteger(), primary_key=True),
        sa.Column("category", sa.String(4), primary_key=True),
        sa.Column("fangraphs_id", sa.String(20), nullable=False),
        sa.Column("stuff_plus", sa.Float(), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
    )


def downgrade():
    op.drop_table("fangraphs_stuff")
