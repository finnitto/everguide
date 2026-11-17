from alembic import op
import sqlalchemy as sa

revision = "0007_verification_run_tracking"
down_revision = "0006_website_verification"
branch_labels = None
depends_on = None

def upgrade():
    op.create_table(
        "website_verification_runs",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("celery_task_id", sa.String(100), nullable=True),
        sa.Column("status", sa.String(30), nullable=False, server_default="queued"),
        sa.Column("requested_limit", sa.Integer(), nullable=False, server_default="50"),
        sa.Column("total", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("checked", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("outcomes", sa.JSON(), nullable=False),
        sa.Column("error_message", sa.Text(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("started_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("completed_at", sa.DateTime(timezone=True), nullable=True),
    )
    op.create_index("ix_website_verification_runs_celery_task_id", "website_verification_runs", ["celery_task_id"])
    op.create_index("ix_website_verification_runs_status", "website_verification_runs", ["status"])

def downgrade():
    op.drop_table("website_verification_runs")
