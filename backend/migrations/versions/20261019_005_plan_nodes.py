"""Persist immutable Plan IR execution attempts and recovery receipts."""
from alembic import op
import sqlalchemy as sa

revision = "20261019_005"
down_revision = "20261018_004"
branch_labels = None
depends_on = None


def upgrade():
    if sa.inspect(op.get_bind()).has_table("plan_node_tasks"):
        return
    op.create_table("plan_node_tasks",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("run_id", sa.String(80), nullable=False),
        sa.Column("plan_version", sa.Integer(), nullable=False),
        sa.Column("node_id", sa.String(40), nullable=False),
        sa.Column("attempt", sa.Integer(), nullable=False),
        sa.Column("status", sa.String(20), nullable=False),
        sa.Column("inputs_hash", sa.String(64), nullable=False),
        sa.Column("inputs", sa.JSON(), nullable=False),
        sa.Column("output", sa.JSON(), nullable=False),
        sa.Column("state", sa.JSON(), nullable=False),
        sa.Column("invocation_id", sa.String(80), sa.ForeignKey("tool_invocations.invocation_id", ondelete="SET NULL")),
        sa.Column("job_id", sa.String(80), sa.ForeignKey("jobs.job_id", ondelete="SET NULL")),
        sa.Column("artifact_ids", sa.JSON(), nullable=False),
        sa.Column("estimated_cost", sa.Float(), nullable=False),
        sa.Column("error", sa.JSON(none_as_null=True)),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(["run_id", "plan_version"], ["agent_plan_versions.run_id", "agent_plan_versions.version"]),
        sa.UniqueConstraint("run_id", "plan_version", "node_id", "attempt", name="uq_plan_node_attempt"),
        sa.CheckConstraint("attempt >= 1 AND estimated_cost >= 0", name="ck_plan_node_limits"))
    op.create_index("ix_plan_node_tasks_run_id", "plan_node_tasks", ["run_id"])
    op.create_index("ix_plan_node_tasks_status", "plan_node_tasks", ["status"])


def downgrade():
    if sa.inspect(op.get_bind()).has_table("plan_node_tasks"):
        op.drop_table("plan_node_tasks")
