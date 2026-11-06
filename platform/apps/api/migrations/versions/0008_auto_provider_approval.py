from alembic import op
import sqlalchemy as sa

revision = "0008_auto_provider_approval"
down_revision = "0007_verification_run_tracking"
branch_labels = None
depends_on = None

def upgrade():
    op.add_column("website_verifications", sa.Column("extracted_data", sa.JSON(), nullable=True))

def downgrade():
    op.drop_column("website_verifications", "extracted_data")
