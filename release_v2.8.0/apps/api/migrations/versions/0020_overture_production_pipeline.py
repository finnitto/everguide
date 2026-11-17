"""Persist Overture imports, evidence assessments and publication outcomes."""
from alembic import op
import sqlalchemy as sa

revision = "0020_overture_feed"
down_revision = "0019_identity_assessment_runs"
branch_labels = None
depends_on = None


def upgrade():
    op.create_table(
        "overture_import_runs",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("status", sa.String(24), nullable=False, server_default="queued"),
        sa.Column("source_release", sa.String(80)),
        sa.Column("records_received", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("records_imported", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("records_updated", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("records_processed", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("outcomes", sa.JSON(), nullable=False, server_default="{}"),
        sa.Column("celery_task_id", sa.String(100)),
        sa.Column("error_message", sa.Text()),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.Column("started_at", sa.DateTime(timezone=True)),
        sa.Column("completed_at", sa.DateTime(timezone=True)),
    )
    op.create_index("ix_overture_import_runs_status", "overture_import_runs", ["status"])
    op.create_index("ix_overture_import_runs_celery_task_id", "overture_import_runs", ["celery_task_id"])

    op.create_table(
        "overture_candidates",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("gers_id", sa.String(80), nullable=False),
        sa.Column("source_release", sa.String(80)),
        sa.Column("candidate_name", sa.String(240), nullable=False),
        sa.Column("postcode", sa.String(12)),
        sa.Column("status", sa.String(32), nullable=False, server_default="awaiting_enrichment"),
        sa.Column("outcome", sa.String(32), nullable=False, server_default="awaiting_enrichment"),
        sa.Column("raw_data", sa.JSON(), nullable=False, server_default="{}"),
        sa.Column("assessment", sa.JSON(), nullable=False, server_default="{}"),
        sa.Column("first_party_evidence", sa.JSON(), nullable=False, server_default="{}"),
        sa.Column("source_observation_id", sa.Integer(), sa.ForeignKey("source_observations.id", ondelete="SET NULL")),
        sa.Column("provider_id", sa.Integer(), sa.ForeignKey("providers.id", ondelete="SET NULL")),
        sa.Column("branch_id", sa.Integer(), sa.ForeignKey("branches.id", ondelete="SET NULL")),
        sa.Column("last_import_run_id", sa.Integer(), sa.ForeignKey("overture_import_runs.id", ondelete="SET NULL")),
        sa.Column("last_checked_at", sa.DateTime(timezone=True)),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.UniqueConstraint("gers_id", name="uq_overture_candidates_gers_id"),
    )
    for name, column in [
        ("ix_overture_candidates_candidate_name", "candidate_name"),
        ("ix_overture_candidates_postcode", "postcode"),
        ("ix_overture_candidates_status", "status"),
        ("ix_overture_candidates_outcome", "outcome"),
        ("ix_overture_candidates_source_observation_id", "source_observation_id"),
        ("ix_overture_candidates_provider_id", "provider_id"),
        ("ix_overture_candidates_branch_id", "branch_id"),
        ("ix_overture_candidates_last_import_run_id", "last_import_run_id"),
    ]:
        op.create_index(name, "overture_candidates", [column])


def downgrade():
    op.drop_table("overture_candidates")
    op.drop_table("overture_import_runs")
