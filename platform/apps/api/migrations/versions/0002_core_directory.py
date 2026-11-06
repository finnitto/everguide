from alembic import op
import sqlalchemy as sa
revision = "0002_core_directory"
down_revision = "0001_enable_postgis"
branch_labels = None
depends_on = None

def upgrade():
    op.create_table("providers",
        sa.Column("id",sa.Integer(),primary_key=True),sa.Column("trading_name",sa.String(240),nullable=False),sa.Column("registered_name",sa.String(240)),sa.Column("website",sa.String(500)),sa.Column("provider_type",sa.String(40),nullable=False,server_default="funeral_director"),sa.Column("status",sa.String(30),nullable=False,server_default="draft"),sa.Column("verification_status",sa.String(30),nullable=False,server_default="unverified"),sa.Column("notes",sa.Text()),sa.Column("created_at",sa.DateTime(timezone=True),nullable=False),sa.Column("updated_at",sa.DateTime(timezone=True),nullable=False))
    op.create_index("ix_providers_trading_name","providers",["trading_name"]); op.create_index("ix_providers_status","providers",["status"])
    op.create_table("branches",sa.Column("id",sa.Integer(),primary_key=True),sa.Column("provider_id",sa.Integer(),sa.ForeignKey("providers.id",ondelete="CASCADE"),nullable=False),sa.Column("branch_name",sa.String(240),nullable=False),sa.Column("address_line_1",sa.String(240),nullable=False),sa.Column("address_line_2",sa.String(240)),sa.Column("town_city",sa.String(120),nullable=False),sa.Column("county",sa.String(120)),sa.Column("postcode",sa.String(12),nullable=False),sa.Column("telephone",sa.String(40)),sa.Column("email",sa.String(254)),sa.Column("website",sa.String(500)),sa.Column("latitude",sa.Float()),sa.Column("longitude",sa.Float()),sa.Column("services",sa.JSON(),nullable=False),sa.Column("status",sa.String(30),nullable=False,server_default="draft"),sa.Column("created_at",sa.DateTime(timezone=True),nullable=False),sa.Column("updated_at",sa.DateTime(timezone=True),nullable=False))
    for col in ["provider_id","town_city","postcode","status"]: op.create_index(f"ix_branches_{col}","branches",[col])
    op.create_index("ix_branches_location","branches",["town_city","postcode"])
    op.create_table("source_observations",sa.Column("id",sa.Integer(),primary_key=True),sa.Column("provider_id",sa.Integer(),sa.ForeignKey("providers.id",ondelete="SET NULL")),sa.Column("branch_id",sa.Integer(),sa.ForeignKey("branches.id",ondelete="SET NULL")),sa.Column("source_type",sa.String(60),nullable=False),sa.Column("source_name",sa.String(240),nullable=False),sa.Column("source_url",sa.String(1000)),sa.Column("retrieved_at",sa.DateTime(timezone=True),nullable=False),sa.Column("confidence",sa.Float()),sa.Column("observed_data",sa.JSON(),nullable=False),sa.Column("review_status",sa.String(30),nullable=False,server_default="pending"),sa.Column("notes",sa.Text()))
    for col in ["provider_id","branch_id","review_status"]: op.create_index(f"ix_source_observations_{col}","source_observations",[col])
    op.create_table("audit_events",sa.Column("id",sa.Integer(),primary_key=True),sa.Column("entity_type",sa.String(40),nullable=False),sa.Column("entity_id",sa.Integer(),nullable=False),sa.Column("action",sa.String(60),nullable=False),sa.Column("detail",sa.JSON(),nullable=False),sa.Column("actor",sa.String(120),nullable=False,server_default="local-admin"),sa.Column("created_at",sa.DateTime(timezone=True),nullable=False))
    op.create_index("ix_audit_events_entity_id","audit_events",["entity_id"])

def downgrade():
    op.drop_table("audit_events"); op.drop_table("source_observations"); op.drop_table("branches"); op.drop_table("providers")
