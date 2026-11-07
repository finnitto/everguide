from alembic import op
import sqlalchemy as sa

revision = "0009_expand_status"
down_revision = "0008_auto_provider_approval"
branch_labels = None
depends_on = None

def upgrade():
    # Status values now include longer automatic-approval exception states.
    op.alter_column(
        "website_discovery_results",
        "status",
        existing_type=sa.String(length=30),
        type_=sa.String(length=80),
        existing_nullable=False,
    )

def downgrade():
    # Keep the widened column: existing rows may contain values longer than 30.
    pass
