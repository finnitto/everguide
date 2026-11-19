"""Attach website-derived branch proposals to one verified Overture branch link."""
from alembic import op
import sqlalchemy as sa

revision = "0022_branch_overture_provenance"
down_revision = "0021_overture_company_links"
branch_labels = None
depends_on = None


def upgrade():
    op.add_column(
        "company_branch_proposals",
        sa.Column("overture_company_link_id", sa.Integer(), nullable=True),
    )
    op.create_foreign_key(
        "fk_company_branch_proposals_overture_company_link_id",
        "company_branch_proposals",
        "overture_company_links",
        ["overture_company_link_id"],
        ["id"],
        ondelete="RESTRICT",
    )
    op.create_index(
        "ix_company_branch_proposals_overture_company_link_id",
        "company_branch_proposals",
        ["overture_company_link_id"],
    )


def downgrade():
    op.drop_index(
        "ix_company_branch_proposals_overture_company_link_id",
        table_name="company_branch_proposals",
    )
    op.drop_constraint(
        "fk_company_branch_proposals_overture_company_link_id",
        "company_branch_proposals",
        type_="foreignkey",
    )
    op.drop_column("company_branch_proposals", "overture_company_link_id")
