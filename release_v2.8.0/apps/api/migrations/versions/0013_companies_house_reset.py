"""Clean development directory and establish Companies House candidate intake.

This is intentionally destructive to the pre-v2.0 development directory data.
It preserves the database, schema migration history and all application
configuration. The reset is one-time because Alembic records this revision.
"""
from alembic import op
import sqlalchemy as sa

revision = "0013_ch_reset"
down_revision = "0012_display_name"
branch_labels = None
depends_on = None

def upgrade():
    op.create_table(
        "companies_house_runs",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("status", sa.String(24), nullable=False, server_default="queued"),
        sa.Column("sic_codes", sa.JSON(), nullable=False, server_default="[]"),
        sa.Column("total_results", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("imported", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("pages_fetched", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("error_message", sa.Text(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("started_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("completed_at", sa.DateTime(timezone=True), nullable=True),
    )
    op.create_index("ix_companies_house_runs_status", "companies_house_runs", ["status"])
    op.create_table(
        "companies_house_candidates",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("company_number", sa.String(16), nullable=False),
        sa.Column("company_name", sa.String(240), nullable=False),
        sa.Column("company_status", sa.String(40), nullable=False),
        sa.Column("company_type", sa.String(60), nullable=True),
        sa.Column("sic_codes", sa.JSON(), nullable=False, server_default="[]"),
        sa.Column("registered_office_address", sa.JSON(), nullable=False, server_default="{}"),
        sa.Column("date_of_creation", sa.String(20), nullable=True),
        sa.Column("company_profile_url", sa.String(500), nullable=True),
        sa.Column("source_run_id", sa.Integer(), sa.ForeignKey("companies_house_runs.id", ondelete="SET NULL"), nullable=True),
        sa.Column("classification", sa.String(40), nullable=False, server_default="unclassified"),
        sa.Column("review_status", sa.String(24), nullable=False, server_default="candidate"),
        sa.Column("raw_company_record", sa.JSON(), nullable=False, server_default="{}"),
        sa.Column("first_seen_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("last_seen_at", sa.DateTime(timezone=True), nullable=False),
    )
    op.create_index("ix_companies_house_candidates_company_number", "companies_house_candidates", ["company_number"], unique=True)
    op.create_index("ix_companies_house_candidates_company_name", "companies_house_candidates", ["company_name"])
    op.create_index("ix_companies_house_candidates_company_status", "companies_house_candidates", ["company_status"])
    op.create_index("ix_companies_house_candidates_source_run_id", "companies_house_candidates", ["source_run_id"])
    op.create_index("ix_companies_house_candidates_classification", "companies_house_candidates", ["classification"])
    op.create_index("ix_companies_house_candidates_review_status", "companies_house_candidates", ["review_status"])

    # Clear the early development directory and its operational discovery data.
    # The TRUNCATE is executed exactly once by this migration. Schema and
    # Alembic migration history remain intact. No app user table exists here.
    op.execute("TRUNCATE TABLE provider_quality_actions, website_verifications, website_verification_runs, website_evidence_checks, source_permissions, website_discovery_results, source_observations, discovery_runs, branches, providers, audit_events RESTART IDENTITY CASCADE")
    op.execute("INSERT INTO audit_events (entity_type, entity_id, action, detail, actor, created_at) VALUES ('system', 0, 'development_directory_reset', '{\"release\":\"2.0.0\",\"reason\":\"Companies House-led discovery foundation\",\"cleared\":[\"providers\",\"branches\",\"source_observations\",\"website_discovery\",\"website_verification\",\"correction_proposals\",\"discovery_runs\"]}'::json, 'system-migration', now())")

def downgrade():
    # A downgrade cannot restore intentionally cleared development data.
    op.drop_index("ix_companies_house_candidates_review_status", table_name="companies_house_candidates")
    op.drop_index("ix_companies_house_candidates_classification", table_name="companies_house_candidates")
    op.drop_index("ix_companies_house_candidates_source_run_id", table_name="companies_house_candidates")
    op.drop_index("ix_companies_house_candidates_company_status", table_name="companies_house_candidates")
    op.drop_index("ix_companies_house_candidates_company_name", table_name="companies_house_candidates")
    op.drop_index("ix_companies_house_candidates_company_number", table_name="companies_house_candidates")
    op.drop_table("companies_house_candidates")
    op.drop_index("ix_companies_house_runs_status", table_name="companies_house_runs")
    op.drop_table("companies_house_runs")
