"""Add separate pricing, membership, regulatory and revalidation evidence domains."""
from alembic import op
import sqlalchemy as sa

revision = "0023_stage3_evidence"
down_revision = "0022_branch_overture_provenance"
branch_labels = None
depends_on = None


def _evidence_columns():
    return [
        sa.Column("source_name", sa.String(240), nullable=False),
        sa.Column("source_url", sa.String(1000), nullable=False),
        sa.Column("source_rights_basis", sa.Text(), nullable=False),
        sa.Column("source_permission_id", sa.Integer(), sa.ForeignKey("source_permissions.id", ondelete="SET NULL"), nullable=True),
        sa.Column("source_retrieved_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.Column("evidence_sha256", sa.String(64), nullable=False),
        sa.Column("evidence_excerpt", sa.Text(), nullable=True),
        sa.Column("evidence_payload", sa.JSON(), nullable=False, server_default=sa.text("'{}'")),
        sa.Column("review_status", sa.String(24), nullable=False, server_default="pending"),
        sa.Column("reviewed_by", sa.String(120), nullable=True),
        sa.Column("reviewed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("review_notes", sa.Text(), nullable=True),
        sa.Column("last_checked_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
    ]


def upgrade():
    op.add_column(
        "providers",
        sa.Column("business_form", sa.String(30), nullable=False, server_default="unknown"),
    )

    op.create_table(
        "pricing_evidence",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("provider_id", sa.Integer(), sa.ForeignKey("providers.id", ondelete="CASCADE"), nullable=False),
        sa.Column("branch_id", sa.Integer(), sa.ForeignKey("branches.id", ondelete="RESTRICT"), nullable=True),
        sa.Column("service_category", sa.String(60), nullable=False),
        sa.Column("service_name", sa.String(240), nullable=False),
        sa.Column("fee_type", sa.String(60), nullable=False),
        sa.Column("amount", sa.Numeric(12, 2), nullable=False),
        sa.Column("amount_upper", sa.Numeric(12, 2), nullable=True),
        sa.Column("currency", sa.String(3), nullable=False, server_default="GBP"),
        sa.Column("price_basis", sa.String(24), nullable=False, server_default="fixed"),
        sa.Column("includes", sa.JSON(), nullable=False, server_default=sa.text("'[]'")),
        sa.Column("excludes", sa.JSON(), nullable=False, server_default=sa.text("'[]'")),
        sa.Column("applicability", sa.JSON(), nullable=False, server_default=sa.text("'{}'")),
        sa.Column("effective_from", sa.DateTime(timezone=True), nullable=True),
        sa.Column("effective_to", sa.DateTime(timezone=True), nullable=True),
        *_evidence_columns(),
        sa.CheckConstraint("amount >= 0", name="ck_pricing_evidence_amount_non_negative"),
        sa.CheckConstraint("amount_upper IS NULL OR amount_upper >= amount", name="ck_pricing_evidence_amount_upper"),
    )
    op.create_index("ix_pricing_evidence_provider_id", "pricing_evidence", ["provider_id"])
    op.create_index("ix_pricing_evidence_branch_id", "pricing_evidence", ["branch_id"])
    op.create_index("ix_pricing_evidence_service_category", "pricing_evidence", ["service_category"])
    op.create_index("ix_pricing_evidence_review_status", "pricing_evidence", ["review_status"])
    op.create_index("ix_pricing_evidence_source_permission_id", "pricing_evidence", ["source_permission_id"])
    op.create_index("ix_pricing_evidence_expires_at", "pricing_evidence", ["expires_at"])

    op.create_table(
        "membership_evidence",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("provider_id", sa.Integer(), sa.ForeignKey("providers.id", ondelete="CASCADE"), nullable=False),
        sa.Column("branch_id", sa.Integer(), sa.ForeignKey("branches.id", ondelete="RESTRICT"), nullable=True),
        sa.Column("scheme_code", sa.String(32), nullable=False),
        sa.Column("membership_number", sa.String(100), nullable=True),
        sa.Column("member_name", sa.String(240), nullable=True),
        sa.Column("reported_status", sa.String(32), nullable=False, server_default="unknown"),
        sa.Column("applicability_status", sa.String(24), nullable=False, server_default="unknown"),
        sa.Column("valid_from", sa.DateTime(timezone=True), nullable=True),
        sa.Column("valid_to", sa.DateTime(timezone=True), nullable=True),
        *_evidence_columns(),
    )
    op.create_index("ix_membership_evidence_provider_id", "membership_evidence", ["provider_id"])
    op.create_index("ix_membership_evidence_branch_id", "membership_evidence", ["branch_id"])
    op.create_index("ix_membership_evidence_scheme_code", "membership_evidence", ["scheme_code"])
    op.create_index("ix_membership_evidence_reported_status", "membership_evidence", ["reported_status"])
    op.create_index("ix_membership_evidence_review_status", "membership_evidence", ["review_status"])
    op.create_index("ix_membership_evidence_source_permission_id", "membership_evidence", ["source_permission_id"])
    op.create_index("ix_membership_evidence_expires_at", "membership_evidence", ["expires_at"])

    op.create_table(
        "regulatory_evidence",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("provider_id", sa.Integer(), sa.ForeignKey("providers.id", ondelete="CASCADE"), nullable=False),
        sa.Column("branch_id", sa.Integer(), sa.ForeignKey("branches.id", ondelete="RESTRICT"), nullable=True),
        sa.Column("regulator_code", sa.String(32), nullable=False),
        sa.Column("reference_number", sa.String(100), nullable=True),
        sa.Column("permissions", sa.JSON(), nullable=False, server_default=sa.text("'[]'")),
        sa.Column("reported_status", sa.String(32), nullable=False, server_default="unknown"),
        sa.Column("applicability_status", sa.String(24), nullable=False, server_default="unknown"),
        sa.Column("valid_from", sa.DateTime(timezone=True), nullable=True),
        sa.Column("valid_to", sa.DateTime(timezone=True), nullable=True),
        *_evidence_columns(),
    )
    op.create_index("ix_regulatory_evidence_provider_id", "regulatory_evidence", ["provider_id"])
    op.create_index("ix_regulatory_evidence_branch_id", "regulatory_evidence", ["branch_id"])
    op.create_index("ix_regulatory_evidence_regulator_code", "regulatory_evidence", ["regulator_code"])
    op.create_index("ix_regulatory_evidence_reported_status", "regulatory_evidence", ["reported_status"])
    op.create_index("ix_regulatory_evidence_review_status", "regulatory_evidence", ["review_status"])
    op.create_index("ix_regulatory_evidence_source_permission_id", "regulatory_evidence", ["source_permission_id"])
    op.create_index("ix_regulatory_evidence_expires_at", "regulatory_evidence", ["expires_at"])

    op.create_table(
        "evidence_revalidation_requests",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("idempotency_key", sa.String(128), nullable=False),
        sa.Column("domain", sa.String(24), nullable=False),
        sa.Column("evidence_id", sa.Integer(), nullable=False),
        sa.Column("provider_id", sa.Integer(), sa.ForeignKey("providers.id", ondelete="CASCADE"), nullable=False),
        sa.Column("branch_id", sa.Integer(), sa.ForeignKey("branches.id", ondelete="RESTRICT"), nullable=True),
        sa.Column("reason", sa.Text(), nullable=False),
        sa.Column("status", sa.String(24), nullable=False, server_default="requested"),
        sa.Column("attempt_count", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("max_attempts", sa.Integer(), nullable=False, server_default="4"),
        sa.Column("next_attempt_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("last_attempt_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("last_error", sa.Text(), nullable=True),
        sa.Column("requested_by", sa.String(120), nullable=False),
        sa.Column("completed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.UniqueConstraint("idempotency_key", name="uq_evidence_revalidation_requests_idempotency_key"),
        sa.CheckConstraint("attempt_count >= 0 AND attempt_count <= max_attempts", name="ck_evidence_revalidation_attempt_bounds"),
        sa.CheckConstraint("max_attempts >= 1 AND max_attempts <= 4", name="ck_evidence_revalidation_max_attempts"),
    )
    op.create_index("ix_evidence_revalidation_requests_domain", "evidence_revalidation_requests", ["domain"])
    op.create_index("ix_evidence_revalidation_requests_provider_id", "evidence_revalidation_requests", ["provider_id"])
    op.create_index("ix_evidence_revalidation_requests_branch_id", "evidence_revalidation_requests", ["branch_id"])
    op.create_index("ix_evidence_revalidation_requests_status", "evidence_revalidation_requests", ["status"])
    op.create_index("ix_evidence_revalidation_requests_next_attempt_at", "evidence_revalidation_requests", ["next_attempt_at"])

    op.create_table(
        "evidence_revalidation_attempts",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("request_id", sa.Integer(), sa.ForeignKey("evidence_revalidation_requests.id", ondelete="CASCADE"), nullable=False),
        sa.Column("idempotency_key", sa.String(128), nullable=False),
        sa.Column("attempt_number", sa.Integer(), nullable=False),
        sa.Column("outcome", sa.String(24), nullable=False),
        sa.Column("failure_class", sa.String(60), nullable=True),
        sa.Column("source_url", sa.String(1000), nullable=True),
        sa.Column("evidence_sha256", sa.String(64), nullable=True),
        sa.Column("detail", sa.Text(), nullable=True),
        sa.Column("checked_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("actor", sa.String(120), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.UniqueConstraint("request_id", "idempotency_key", name="uq_evidence_revalidation_attempt_request_key"),
        sa.UniqueConstraint("request_id", "attempt_number", name="uq_evidence_revalidation_attempt_number"),
    )
    op.create_index("ix_evidence_revalidation_attempts_request_id", "evidence_revalidation_attempts", ["request_id"])


def downgrade():
    op.drop_index("ix_evidence_revalidation_attempts_request_id", table_name="evidence_revalidation_attempts")
    op.drop_table("evidence_revalidation_attempts")
    op.drop_index("ix_evidence_revalidation_requests_next_attempt_at", table_name="evidence_revalidation_requests")
    op.drop_index("ix_evidence_revalidation_requests_status", table_name="evidence_revalidation_requests")
    op.drop_index("ix_evidence_revalidation_requests_branch_id", table_name="evidence_revalidation_requests")
    op.drop_index("ix_evidence_revalidation_requests_provider_id", table_name="evidence_revalidation_requests")
    op.drop_index("ix_evidence_revalidation_requests_domain", table_name="evidence_revalidation_requests")
    op.drop_table("evidence_revalidation_requests")
    for table in ("regulatory_evidence", "membership_evidence", "pricing_evidence"):
        op.drop_table(table)
    op.drop_column("providers", "business_form")
