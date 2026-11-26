"""Add optional option grouping to pricing evidence."""
from alembic import op
import sqlalchemy as sa

revision = "0024_pricing_option_groups"
down_revision = "0023_stage3_evidence"
branch_labels = None
depends_on = None


def upgrade():
    op.add_column("pricing_evidence", sa.Column("option_group_id", sa.String(64), nullable=True))
    op.add_column("pricing_evidence", sa.Column("option_group_name", sa.String(240), nullable=True))
    op.create_index("ix_pricing_evidence_option_group_id", "pricing_evidence", ["option_group_id"])


def downgrade():
    op.drop_index("ix_pricing_evidence_option_group_id", table_name="pricing_evidence")
    op.drop_column("pricing_evidence", "option_group_name")
    op.drop_column("pricing_evidence", "option_group_id")
