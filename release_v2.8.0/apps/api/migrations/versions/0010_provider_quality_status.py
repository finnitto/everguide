from alembic import op
import sqlalchemy as sa

revision = "0010_provider_quality"
down_revision = "0009_expand_status"
branch_labels = None
depends_on = None

def upgrade():
    op.add_column("providers", sa.Column("quality_status", sa.String(length=24), nullable=False, server_default="unassessed"))
    op.create_index("ix_providers_quality_status", "providers", ["quality_status"], unique=False)
    # Flag obvious non-provider and generic records for review without deleting or
    # unpublishing them. The admin quality queue provides the evidence for decisions.
    op.execute("""
        UPDATE providers SET quality_status='needs_review'
        WHERE lower(trim(trading_name)) IN ('admin','administrator','home','welcome','localfuneral','ipswich borough council')
           OR lower(coalesce(website,'')) ~ '(cemetery|cemeteries|crematorium|council|funeral.?directory|localfuneral)'
    """)

def downgrade():
    op.drop_index("ix_providers_quality_status", table_name="providers")
    op.drop_column("providers", "quality_status")
