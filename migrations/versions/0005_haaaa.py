"""Store frozen-reference expected HAA and per-pitch HAAAA."""

import sqlalchemy as sa
from alembic import op

revision = "0005_haaaa"
down_revision = "0004_approach_angles"
branch_labels = None
depends_on = None


def upgrade():
    op.add_column("pitches", sa.Column("pitcher_throws", sa.String(1), nullable=True))
    op.add_column("pitches", sa.Column("expected_haa", sa.Float(), nullable=True))
    op.add_column("pitches", sa.Column("haaaa", sa.Float(), nullable=True))
    op.add_column("pitches", sa.Column("haaaa_model_id", sa.String(64), nullable=True))


def downgrade():
    with op.batch_alter_table("pitches") as batch:
        for field in ("haaaa_model_id", "haaaa", "expected_haa", "pitcher_throws"):
            batch.drop_column(field)
