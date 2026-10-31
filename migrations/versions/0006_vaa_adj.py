"""Store frozen-reference expected VAA and location-adjusted VAA."""

import sqlalchemy as sa
from alembic import op

revision = "0006_vaa_adj"
down_revision = "0005_haaaa"
branch_labels = None
depends_on = None


def upgrade():
    op.add_column("pitches", sa.Column("expected_vaa", sa.Float(), nullable=True))
    op.add_column("pitches", sa.Column("vaa_adj", sa.Float(), nullable=True))
    op.add_column("pitches", sa.Column("vaa_adj_model_id", sa.String(64), nullable=True))


def downgrade():
    with op.batch_alter_table("pitches") as batch:
        for field in ("vaa_adj_model_id", "vaa_adj", "expected_vaa"):
            batch.drop_column(field)
