from alembic import op

revision = "0001_enable_postgis"
down_revision = None
branch_labels = None
depends_on = None

def upgrade():
    op.execute("CREATE EXTENSION IF NOT EXISTS postgis")

def downgrade():
    # Keep the extension installed; other schema objects may depend on it.
    pass
