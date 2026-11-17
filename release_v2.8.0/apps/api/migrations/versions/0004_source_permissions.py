from alembic import op
import sqlalchemy as sa
revision = "0004_source_permissions"
down_revision = "0003_discovery_runs"
branch_labels = None
depends_on = None
def upgrade():
    op.create_table("source_permissions", sa.Column("id",sa.Integer(),primary_key=True), sa.Column("provider_id",sa.Integer(),sa.ForeignKey("providers.id",ondelete="CASCADE"),nullable=False), sa.Column("source_url",sa.String(1000),nullable=False), sa.Column("source_domain",sa.String(255),nullable=False), sa.Column("permission_status",sa.String(30),nullable=False,server_default="pending"), sa.Column("permission_basis",sa.Text(),nullable=False), sa.Column("permission_reference",sa.String(500)), sa.Column("approved_by",sa.String(120)), sa.Column("approved_at",sa.DateTime(timezone=True)), sa.Column("created_at",sa.DateTime(timezone=True),nullable=False))
    op.create_index("ix_source_permissions_provider_id","source_permissions",["provider_id"])
    op.create_index("ix_source_permissions_source_domain","source_permissions",["source_domain"])
    op.create_index("ix_source_permissions_permission_status","source_permissions",["permission_status"])
    op.create_table("website_evidence_checks", sa.Column("id",sa.Integer(),primary_key=True), sa.Column("source_permission_id",sa.Integer(),sa.ForeignKey("source_permissions.id",ondelete="CASCADE"),nullable=False), sa.Column("provider_id",sa.Integer(),sa.ForeignKey("providers.id",ondelete="CASCADE"),nullable=False), sa.Column("checked_at",sa.DateTime(timezone=True),nullable=False), sa.Column("status",sa.String(30),nullable=False), sa.Column("http_status",sa.Integer()), sa.Column("page_title",sa.String(500)), sa.Column("content_sha256",sa.String(64)), sa.Column("detail",sa.Text()))
    op.create_index("ix_website_evidence_checks_source_permission_id","website_evidence_checks",["source_permission_id"])
    op.create_index("ix_website_evidence_checks_provider_id","website_evidence_checks",["provider_id"])
def downgrade():
    op.drop_table("website_evidence_checks")
    op.drop_table("source_permissions")
