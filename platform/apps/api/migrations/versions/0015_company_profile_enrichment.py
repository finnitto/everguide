"""Add Companies House profile enrichment fields."""
from alembic import op
import sqlalchemy as sa

revision = "0015_ch_profiles"
down_revision = "0014_ch_classify"
branch_labels = None
depends_on = None

def upgrade():
    op.add_column("companies_house_candidates", sa.Column("profile_status", sa.String(24), nullable=False, server_default="not_requested"))
    op.add_column("companies_house_candidates", sa.Column("profile_checked_at", sa.DateTime(timezone=True), nullable=True))
    op.add_column("companies_house_candidates", sa.Column("profile_error", sa.Text(), nullable=True))
    op.add_column("companies_house_candidates", sa.Column("company_profile", sa.JSON(), nullable=False, server_default=sa.text("'{}'")))
    op.add_column("companies_house_candidates", sa.Column("previous_company_names", sa.JSON(), nullable=False, server_default=sa.text("'[]'")))
    op.create_index("ix_companies_house_candidates_profile_status", "companies_house_candidates", ["profile_status"])

def downgrade():
    op.drop_index("ix_companies_house_candidates_profile_status", table_name="companies_house_candidates")
    op.drop_column("companies_house_candidates", "previous_company_names")
    op.drop_column("companies_house_candidates", "company_profile")
    op.drop_column("companies_house_candidates", "profile_error")
    op.drop_column("companies_house_candidates", "profile_checked_at")
    op.drop_column("companies_house_candidates", "profile_status")
