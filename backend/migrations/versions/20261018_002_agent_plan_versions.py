"""Add immutable Agent story plans and durable preview attempts."""

from alembic import op
import sqlalchemy as sa

revision = "20261018_002"
down_revision = "20261018_001"
branch_labels = None
depends_on = None


def upgrade():
    bind = op.get_bind()
    if not sa.inspect(bind).has_table("agent_plan_versions"):
        op.create_table(
            "agent_plan_versions",
            sa.Column("id", sa.Integer(), primary_key=True),
            sa.Column("run_id", sa.String(80), sa.ForeignKey("agent_runs.run_id"), nullable=False),
            sa.Column("version", sa.Integer(), nullable=False),
            sa.Column("author", sa.String(20), nullable=False),
            sa.Column("parent_version", sa.Integer()),
            sa.Column("plan", sa.JSON(), nullable=False),
            sa.Column("story_package", sa.JSON(), nullable=False),
            sa.Column("check", sa.JSON(), nullable=False),
            sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
            sa.UniqueConstraint("run_id", "version", name="uq_agent_plan_run_version"),
            sa.CheckConstraint("version >= 1", name="ck_agent_plan_version_positive"),
        )
        op.create_index("ix_agent_plan_versions_run_id", "agent_plan_versions", ["run_id"])
    if not sa.inspect(bind).has_table("agent_shot_tasks"):
        op.create_table(
            "agent_shot_tasks",
            sa.Column("id", sa.Integer(), primary_key=True),
            sa.Column("run_id", sa.String(80), nullable=False),
            sa.Column("plan_version", sa.Integer(), nullable=False),
            sa.Column("target_type", sa.String(20), nullable=False),
            sa.Column("target_id", sa.String(80), nullable=False),
            sa.Column("attempt", sa.Integer(), nullable=False),
            sa.Column("status", sa.String(20), nullable=False),
            sa.Column("inputs_hash", sa.String(64), nullable=False),
            sa.Column("invocation_id", sa.String(80), sa.ForeignKey("tool_invocations.invocation_id", ondelete="SET NULL")),
            sa.Column("job_id", sa.String(80), sa.ForeignKey("jobs.job_id", ondelete="SET NULL")),
            sa.Column("artifact_ids", sa.JSON(), nullable=False),
            sa.Column("estimated_cost", sa.Float(), nullable=False),
            sa.Column("error", sa.JSON(none_as_null=True)),
            sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
            sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
            sa.ForeignKeyConstraint(["run_id", "plan_version"],
                                    ["agent_plan_versions.run_id", "agent_plan_versions.version"]),
            sa.UniqueConstraint("run_id", "plan_version", "target_type", "target_id", "attempt",
                                name="uq_agent_shot_attempt"),
            sa.CheckConstraint("attempt >= 1", name="ck_agent_shot_attempt_positive"),
        )
        op.create_index("ix_agent_shot_tasks_run_id", "agent_shot_tasks", ["run_id"])
        op.create_index("ix_agent_shot_tasks_status", "agent_shot_tasks", ["status"])


def downgrade():
    for name in ("agent_shot_tasks", "agent_plan_versions"):
        if sa.inspect(op.get_bind()).has_table(name):
            op.drop_table(name)
