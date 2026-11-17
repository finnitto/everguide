"""Add resumable identity assessment run tracking."""
from alembic import op
import sqlalchemy as sa
revision = "0019_identity_assessment_runs"
down_revision = "0018_identity_branch_review"
branch_labels = None
depends_on = None
def upgrade():
    op.create_table("identity_assessment_runs",
        sa.Column("id",sa.Integer(),primary_key=True),
        sa.Column("status",sa.String(24),nullable=False,server_default="queued"),
        sa.Column("total_companies",sa.Integer(),nullable=False,server_default="0"),
        sa.Column("processed_companies",sa.Integer(),nullable=False,server_default="0"),
        sa.Column("identity_reviews_created",sa.Integer(),nullable=False,server_default="0"),
        sa.Column("branch_proposals_created",sa.Integer(),nullable=False,server_default="0"),
        sa.Column("branch_evidence_skipped",sa.Integer(),nullable=False,server_default="0"),
        sa.Column("last_company_candidate_id",sa.Integer(),nullable=False,server_default="0"),
        sa.Column("celery_task_id",sa.String(100)),
        sa.Column("error_message",sa.Text()),
        sa.Column("created_at",sa.DateTime(timezone=True),nullable=False,server_default=sa.func.now()),
        sa.Column("started_at",sa.DateTime(timezone=True)),
        sa.Column("completed_at",sa.DateTime(timezone=True)))
    op.create_index("ix_identity_assessment_runs_status","identity_assessment_runs",["status"])
def downgrade():
    op.drop_table("identity_assessment_runs")
