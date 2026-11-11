"""Mark enrichment runs left active by a terminated worker as interrupted."""
from alembic import op
import sqlalchemy as sa
revision = "0016_ch_interrupted"
down_revision = "0015_ch_profiles"
branch_labels = None
depends_on = None

def upgrade():
    op.execute(sa.text("UPDATE companies_house_runs SET status='interrupted', completed_at=NOW(), error_message=COALESCE(error_message, 'Worker task was stopped before completion; candidates remain eligible for resumption.') WHERE status='enriching'"))

def downgrade():
    pass
