"""Add the Agent capability catalog without changing classic task types."""
from alembic import op
import sqlalchemy as sa

revision = "20261018_001"
down_revision = "20261017_001"
branch_labels = None
depends_on = None


def upgrade():
    columns = {c["name"] for c in sa.inspect(op.get_bind()).get_columns("models")}
    if "capabilities" not in columns:
        op.add_column("models", sa.Column(
            "capabilities", sa.JSON(), nullable=False, server_default=sa.text("('{}')")
        ))


def downgrade():
    columns = {c["name"] for c in sa.inspect(op.get_bind()).get_columns("models")}
    if "capabilities" in columns:
        with op.batch_alter_table("models") as batch:
            batch.drop_column("capabilities")
