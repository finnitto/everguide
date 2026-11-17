"""Add explainable Companies House candidate classification."""
from alembic import op
import sqlalchemy as sa

revision = "0014_ch_classify"
down_revision = "0013_ch_reset"
branch_labels = None
depends_on = None

def upgrade():
    op.add_column("companies_house_candidates", sa.Column("classification_reason", sa.Text(), nullable=True))
    op.add_column("companies_house_candidates", sa.Column("classification_confidence", sa.String(16), nullable=False, server_default="unassessed"))
    op.add_column("companies_house_candidates", sa.Column("classified_at", sa.DateTime(timezone=True), nullable=True))
    op.add_column("companies_house_runs", sa.Column("api_items_per_page", sa.Integer(), nullable=False, server_default="0"))
    op.add_column("companies_house_runs", sa.Column("unique_companies_seen", sa.Integer(), nullable=False, server_default="0"))

def downgrade():
    op.drop_column("companies_house_runs", "unique_companies_seen")
    op.drop_column("companies_house_runs", "api_items_per_page")
    op.drop_column("companies_house_candidates", "classified_at")
    op.drop_column("companies_house_candidates", "classification_confidence")
    op.drop_column("companies_house_candidates", "classification_reason")
