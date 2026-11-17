from alembic import op
import sqlalchemy as sa

revision = "0012_display_name"
down_revision = "0011_quality_actions"
branch_labels = None
depends_on = None


def upgrade():
    op.add_column("providers", sa.Column("display_name", sa.String(length=240), nullable=True))


def downgrade():
    op.drop_column("providers", "display_name")
