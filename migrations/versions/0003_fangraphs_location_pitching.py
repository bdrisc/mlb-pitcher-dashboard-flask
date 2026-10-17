"""Add published Location+ and Pitching+ alongside Stuff+."""

import sqlalchemy as sa
from alembic import op

revision = "0003_fangraphs_models"
down_revision = "0002_fangraphs_stuff"
branch_labels = None
depends_on = None


def upgrade():
    with op.batch_alter_table("fangraphs_stuff") as batch:
        batch.alter_column("stuff_plus", existing_type=sa.Float(), nullable=True)
        batch.add_column(sa.Column("location_plus", sa.Float(), nullable=True))
        batch.add_column(sa.Column("pitching_plus", sa.Float(), nullable=True))


def downgrade():
    with op.batch_alter_table("fangraphs_stuff") as batch:
        batch.drop_column("location_plus")
        batch.drop_column("pitching_plus")
    # Leave Stuff+ nullable to preserve rows that only have other model grades.
