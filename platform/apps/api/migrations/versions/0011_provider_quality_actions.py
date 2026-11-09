from alembic import op
import sqlalchemy as sa

revision = "0011_quality_actions"
down_revision = "0010_provider_quality"
branch_labels = None
depends_on = None

def upgrade():
    op.create_table(
        "provider_quality_actions",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("provider_id", sa.Integer(), sa.ForeignKey("providers.id", ondelete="CASCADE"), nullable=False),
        sa.Column("action_type", sa.String(length=40), nullable=False),
        sa.Column("category", sa.String(length=60), nullable=False),
        sa.Column("proposed_value", sa.JSON(), nullable=False, server_default="{}"),
        sa.Column("evidence", sa.JSON(), nullable=False, server_default="{}"),
        sa.Column("confidence", sa.String(length=20), nullable=False, server_default="review"),
        sa.Column("status", sa.String(length=24), nullable=False, server_default="pending"),
        sa.Column("decision_note", sa.Text(), nullable=True),
        sa.Column("decided_by", sa.String(length=120), nullable=True),
        sa.Column("decided_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
    )
    op.create_index("ix_provider_quality_actions_provider_id", "provider_quality_actions", ["provider_id"])
    op.create_index("ix_provider_quality_actions_action_type", "provider_quality_actions", ["action_type"])
    op.create_index("ix_provider_quality_actions_category", "provider_quality_actions", ["category"])
    op.create_index("ix_provider_quality_actions_status", "provider_quality_actions", ["status"])

def downgrade():
    op.drop_index("ix_provider_quality_actions_status", table_name="provider_quality_actions")
    op.drop_index("ix_provider_quality_actions_category", table_name="provider_quality_actions")
    op.drop_index("ix_provider_quality_actions_action_type", table_name="provider_quality_actions")
    op.drop_index("ix_provider_quality_actions_provider_id", table_name="provider_quality_actions")
    op.drop_table("provider_quality_actions")
