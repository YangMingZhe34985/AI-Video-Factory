"""Add nullable v3 Agent identities to the existing tool ledger."""
from alembic import op
import sqlalchemy as sa

revision = "20261018_003"
down_revision = "20261018_002"
branch_labels = None
depends_on = None


def upgrade():
    columns = {column["name"] for column in sa.inspect(op.get_bind()).get_columns("tool_invocations")}
    for name, sql_type in (("caller_agent", sa.String(40)), ("delegation_id", sa.Integer)):
        if name not in columns:
            op.add_column("tool_invocations", sa.Column(name, sql_type, nullable=True))


def downgrade():
    columns = {column["name"] for column in sa.inspect(op.get_bind()).get_columns("tool_invocations")}
    with op.batch_alter_table("tool_invocations") as batch:
        for name in ("delegation_id", "caller_agent"):
            if name in columns:
                batch.drop_column(name)
