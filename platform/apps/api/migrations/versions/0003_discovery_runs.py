from alembic import op
import sqlalchemy as sa

revision = "0003_discovery_runs"
down_revision = "0002_core_directory"
branch_labels = None
depends_on = None

def upgrade():
    op.create_table(
        "discovery_runs",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("task_id", sa.String(120), nullable=True),
        sa.Column("status", sa.String(30), nullable=False, server_default="queued"),
        sa.Column("scope", sa.String(40), nullable=False, server_default="england"),
        sa.Column("source", sa.String(60), nullable=False, server_default="google_places"),
        sa.Column("locations_attempted", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("places_found", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("observations_created", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("duplicates_flagged", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("error_message", sa.Text(), nullable=True),
        sa.Column("started_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("completed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
    )
    op.create_index("ix_discovery_runs_task_id", "discovery_runs", ["task_id"])
    op.create_index("ix_discovery_runs_status", "discovery_runs", ["status"])

def downgrade():
    op.drop_index("ix_discovery_runs_status", table_name="discovery_runs")
    op.drop_index("ix_discovery_runs_task_id", table_name="discovery_runs")
    op.drop_table("discovery_runs")
