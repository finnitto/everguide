"""Add company-linked website discovery candidates and run tracking."""
from alembic import op
import sqlalchemy as sa

revision = "0017_company_websites"
down_revision = "0016_ch_interrupted"
branch_labels = None
depends_on = None

def upgrade():
    op.add_column("companies_house_candidates", sa.Column("website_discovery_status", sa.String(length=24), nullable=False, server_default="not_requested"))
    op.add_column("companies_house_candidates", sa.Column("website_discovery_checked_at", sa.DateTime(timezone=True), nullable=True))
    op.add_column("companies_house_candidates", sa.Column("website_discovery_error", sa.Text(), nullable=True))
    op.create_index("ix_companies_house_candidates_website_discovery_status", "companies_house_candidates", ["website_discovery_status"])
    op.create_table(
        "company_website_discovery_runs",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("celery_task_id", sa.String(length=100), nullable=True),
        sa.Column("status", sa.String(length=24), nullable=False, server_default="queued"),
        sa.Column("scope", sa.String(length=24), nullable=False, server_default="england"),
        sa.Column("include_uncertain", sa.Boolean(), nullable=False, server_default=sa.true()),
        sa.Column("batch_size", sa.Integer(), nullable=False, server_default="25"),
        sa.Column("total_candidates", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("processed_candidates", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("results_found", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("websites_checked", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("identity_signals", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("no_results", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("error_message", sa.Text(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.Column("started_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("completed_at", sa.DateTime(timezone=True), nullable=True),
    )
    op.create_index("ix_company_website_discovery_runs_status", "company_website_discovery_runs", ["status"])
    op.create_index("ix_company_website_discovery_runs_celery_task_id", "company_website_discovery_runs", ["celery_task_id"])
    op.create_table(
        "company_website_candidates",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("companies_house_candidate_id", sa.Integer(), sa.ForeignKey("companies_house_candidates.id", ondelete="CASCADE"), nullable=False),
        sa.Column("discovery_run_id", sa.Integer(), sa.ForeignKey("company_website_discovery_runs.id", ondelete="CASCADE"), nullable=False),
        sa.Column("result_title", sa.String(length=500), nullable=False),
        sa.Column("result_url", sa.String(length=1000), nullable=False),
        sa.Column("result_domain", sa.String(length=255), nullable=False),
        sa.Column("result_snippet", sa.String(length=1500), nullable=True),
        sa.Column("search_provider", sa.String(length=40), nullable=False),
        sa.Column("match_score", sa.Float(), nullable=False, server_default="0"),
        sa.Column("verification_status", sa.String(length=32), nullable=False, server_default="not_checked"),
        sa.Column("final_url", sa.String(length=1000), nullable=True),
        sa.Column("http_status", sa.Integer(), nullable=True),
        sa.Column("robots_allowed", sa.Boolean(), nullable=True),
        sa.Column("page_title", sa.String(length=500), nullable=True),
        sa.Column("content_sha256", sa.String(length=64), nullable=True),
        sa.Column("extracted_data", sa.JSON(), nullable=True),
        sa.Column("detail", sa.Text(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.Column("checked_at", sa.DateTime(timezone=True), nullable=True),
    )
    op.create_index("ix_company_website_candidates_companies_house_candidate_id", "company_website_candidates", ["companies_house_candidate_id"])
    op.create_index("ix_company_website_candidates_discovery_run_id", "company_website_candidates", ["discovery_run_id"])
    op.create_index("ix_company_website_candidates_result_domain", "company_website_candidates", ["result_domain"])
    op.create_index("ix_company_website_candidates_verification_status", "company_website_candidates", ["verification_status"])
    op.create_unique_constraint("uq_company_website_candidate_company_url", "company_website_candidates", ["companies_house_candidate_id", "result_url"])

def downgrade():
    op.drop_table("company_website_candidates")
    op.drop_index("ix_company_website_discovery_runs_celery_task_id", table_name="company_website_discovery_runs")
    op.drop_index("ix_company_website_discovery_runs_status", table_name="company_website_discovery_runs")
    op.drop_table("company_website_discovery_runs")
    op.drop_index("ix_companies_house_candidates_website_discovery_status", table_name="companies_house_candidates")
    op.drop_column("companies_house_candidates", "website_discovery_error")
    op.drop_column("companies_house_candidates", "website_discovery_checked_at")
    op.drop_column("companies_house_candidates", "website_discovery_status")
