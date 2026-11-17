from alembic import op
import sqlalchemy as sa
revision = "0005_website_discovery"
down_revision = "0004_source_permissions"
branch_labels = None
depends_on = None
def upgrade():
    op.create_table(
        "website_discovery_results",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("query_region", sa.String(120), nullable=False),
        sa.Column("query_text", sa.String(500), nullable=False),
        sa.Column("result_title", sa.String(500), nullable=False),
        sa.Column("result_url", sa.String(1000), nullable=False),
        sa.Column("result_domain", sa.String(255), nullable=False),
        sa.Column("result_snippet", sa.Text()),
        sa.Column("source_provider", sa.String(40), nullable=False, server_default="brave_search"),
        sa.Column("status", sa.String(30), nullable=False, server_default="candidate"),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
    )
    op.create_index("ix_website_discovery_results_query_region","website_discovery_results",["query_region"])
    op.create_index("ix_website_discovery_results_result_url","website_discovery_results",["result_url"])
    op.create_index("ix_website_discovery_results_result_domain","website_discovery_results",["result_domain"])
    op.create_index("ix_website_discovery_results_status","website_discovery_results",["status"])
def downgrade():
    op.drop_table("website_discovery_results")
