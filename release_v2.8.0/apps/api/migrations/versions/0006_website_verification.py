from alembic import op
import sqlalchemy as sa

revision = "0006_website_verification"
down_revision = "0005_website_discovery"
branch_labels = None
depends_on = None

def upgrade():
    op.create_table(
        "website_verifications",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("candidate_id", sa.Integer(), sa.ForeignKey("website_discovery_results.id", ondelete="CASCADE"), nullable=False),
        sa.Column("checked_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("status", sa.String(40), nullable=False),
        sa.Column("final_url", sa.String(1000)),
        sa.Column("http_status", sa.Integer()),
        sa.Column("content_type", sa.String(160)),
        sa.Column("page_title", sa.String(500)),
        sa.Column("robots_allowed", sa.Boolean()),
        sa.Column("content_sha256", sa.String(64)),
        sa.Column("detail", sa.Text()),
    )
    op.create_index("ix_website_verifications_candidate_id", "website_verifications", ["candidate_id"])
    op.create_index("ix_website_verifications_status", "website_verifications", ["status"])

def downgrade():
    op.drop_table("website_verifications")
