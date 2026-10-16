"""Add the Phase 2 Agent session index and durable command inbox."""

from alembic import op
import sqlalchemy as sa

revision = "20261016_001"
down_revision = "20261014_001"
branch_labels = None
depends_on = None


def upgrade():
    if sa.inspect(op.get_bind()).has_table("agent_runs"):
        return
    op.create_table(
        "agent_runs",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("run_id", sa.String(80), nullable=False, unique=True),
        sa.Column("owner_id", sa.String(80), nullable=False),
        sa.Column("request_key", sa.String(128), nullable=False),
        sa.Column("request", sa.JSON(), nullable=False),
        sa.Column("status", sa.String(40), nullable=False),
        sa.Column("snapshot", sa.JSON(), nullable=False),
        sa.Column("command", sa.JSON(none_as_null=True), nullable=True),
        sa.Column("error", sa.JSON(), nullable=True),
        sa.Column("resume_count", sa.Integer(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.UniqueConstraint("owner_id", "request_key", name="uq_agent_owner_request"),
    )
    op.create_index("ix_agent_runs_owner_id", "agent_runs", ["owner_id"])
    op.create_index("ix_agent_runs_status", "agent_runs", ["status"])


def downgrade():
    op.drop_table("agent_runs")
