"""Add review-only identity and branch proposal queues."""
from alembic import op
import sqlalchemy as sa

revision = "0018_identity_branch_review"
down_revision = "0017_company_websites"
branch_labels = None
depends_on = None

def upgrade():
    op.create_table(
        "company_identity_reviews",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("companies_house_candidate_id", sa.Integer(), sa.ForeignKey("companies_house_candidates.id", ondelete="CASCADE"), nullable=False, unique=True),
        sa.Column("status", sa.String(24), nullable=False, server_default="pending"),
        sa.Column("suggested_trading_name", sa.String(240)),
        sa.Column("suggested_website", sa.String(1000)),
        sa.Column("suggested_domain", sa.String(255)),
        sa.Column("confidence", sa.Float(), nullable=False, server_default="0"),
        sa.Column("evidence", sa.JSON(), nullable=False, server_default="{}"),
        sa.Column("duplicate_leads_collapsed", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("review_notes", sa.Text()),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
    )
    op.create_index("ix_company_identity_reviews_candidate", "company_identity_reviews", ["companies_house_candidate_id"])
    op.create_index("ix_company_identity_reviews_status", "company_identity_reviews", ["status"])
    op.create_index("ix_company_identity_reviews_domain", "company_identity_reviews", ["suggested_domain"])
    op.create_table(
        "company_branch_proposals",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("companies_house_candidate_id", sa.Integer(), sa.ForeignKey("companies_house_candidates.id", ondelete="CASCADE"), nullable=False),
        sa.Column("website_candidate_id", sa.Integer(), sa.ForeignKey("company_website_candidates.id", ondelete="CASCADE"), nullable=False, unique=True),
        sa.Column("status", sa.String(24), nullable=False, server_default="pending"),
        sa.Column("proposed_branch_name", sa.String(240)),
        sa.Column("address_line", sa.String(500)),
        sa.Column("town_city", sa.String(120)),
        sa.Column("postcode", sa.String(12)),
        sa.Column("telephone", sa.String(40)),
        sa.Column("website", sa.String(1000)),
        sa.Column("confidence", sa.Float(), nullable=False, server_default="0"),
        sa.Column("evidence", sa.JSON(), nullable=False, server_default="{}"),
        sa.Column("review_notes", sa.Text()),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
    )
    op.create_index("ix_company_branch_proposals_candidate", "company_branch_proposals", ["companies_house_candidate_id"])
    op.create_index("ix_company_branch_proposals_status", "company_branch_proposals", ["status"])
    op.create_index("ix_company_branch_proposals_postcode", "company_branch_proposals", ["postcode"])

def downgrade():
    op.drop_table("company_branch_proposals")
    op.drop_table("company_identity_reviews")
