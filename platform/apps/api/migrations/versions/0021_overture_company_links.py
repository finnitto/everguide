"""Add auditable Overture-to-Companies House provenance links."""
from alembic import op
import sqlalchemy as sa

revision = "0021_overture_company_links"
down_revision = "0020_overture_feed"
branch_labels = None
depends_on = None


def upgrade():
    op.create_table(
        "overture_company_links",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("overture_candidate_id", sa.Integer(), sa.ForeignKey("overture_candidates.id", ondelete="RESTRICT"), nullable=False),
        sa.Column("companies_house_candidate_id", sa.Integer(), sa.ForeignKey("companies_house_candidates.id", ondelete="RESTRICT"), nullable=False),
        sa.Column("status", sa.String(24), nullable=False, server_default="pending"),
        sa.Column("link_method", sa.String(40), nullable=False, server_default="manual_review"),
        sa.Column("evidence_json", sa.JSON(), nullable=False, server_default="{}"),
        sa.Column("review_notes", sa.Text()),
        sa.Column("reviewed_by", sa.String(120)),
        sa.Column("reviewed_at", sa.DateTime(timezone=True)),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.UniqueConstraint("companies_house_candidate_id", name="uq_overture_company_links_ch_candidate"),
    )
    op.create_index("ix_overture_company_links_overture_candidate_id", "overture_company_links", ["overture_candidate_id"])
    op.create_index("ix_overture_company_links_companies_house_candidate_id", "overture_company_links", ["companies_house_candidate_id"])
    op.create_index("ix_overture_company_links_status", "overture_company_links", ["status"])


def downgrade():
    op.drop_table("overture_company_links")
