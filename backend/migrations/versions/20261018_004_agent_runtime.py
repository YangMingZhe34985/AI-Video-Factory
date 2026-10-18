"""Persist v3 delegations, safe step summaries and versioned workspaces."""

from alembic import op
import sqlalchemy as sa

revision = "20261018_004"
down_revision = "20261018_003"
branch_labels = None
depends_on = None


def upgrade():
    bind = op.get_bind()
    if not sa.inspect(bind).has_table("agent_delegations"):
        op.create_table(
            "agent_delegations",
            sa.Column("id", sa.Integer(), primary_key=True),
            sa.Column("run_id", sa.String(80), sa.ForeignKey("agent_runs.run_id"), nullable=False),
            sa.Column("parent_id", sa.Integer(), sa.ForeignKey("agent_delegations.id")),
            sa.Column("agent", sa.String(40), nullable=False),
            sa.Column("status", sa.String(40), nullable=False),
            sa.Column("task", sa.Text(), nullable=False),
            sa.Column("context_refs", sa.JSON(), nullable=False),
            sa.Column("expected", sa.String(1000), nullable=False),
            sa.Column("depth", sa.Integer(), nullable=False),
            sa.Column("credits_limit", sa.Float(), nullable=False),
            sa.Column("steps", sa.Integer(), nullable=False),
            sa.Column("llm_calls", sa.Integer(), nullable=False),
            sa.Column("output", sa.JSON(none_as_null=True)),
            sa.Column("error", sa.JSON(none_as_null=True)),
            sa.Column("state", sa.JSON(), nullable=False),
            sa.Column("request_key", sa.String(128), nullable=False),
            sa.Column("started_at", sa.DateTime(timezone=True), nullable=False),
            sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
            sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
            sa.UniqueConstraint("run_id", "request_key", name="uq_agent_delegation_request"),
            sa.CheckConstraint("depth >= 0 AND credits_limit >= 0 AND steps >= 0 AND llm_calls >= 0",
                               name="ck_agent_delegation_limits"),
        )
        op.create_index("ix_agent_delegations_run_id", "agent_delegations", ["run_id"])
        op.create_index("ix_agent_delegations_status", "agent_delegations", ["status"])
    if not sa.inspect(bind).has_table("agent_steps"):
        op.create_table(
            "agent_steps",
            sa.Column("id", sa.Integer(), primary_key=True),
            sa.Column("run_id", sa.String(80), sa.ForeignKey("agent_runs.run_id"), nullable=False),
            sa.Column("delegation_id", sa.Integer(), sa.ForeignKey("agent_delegations.id"), nullable=False),
            sa.Column("step", sa.Integer(), nullable=False),
            sa.Column("kind", sa.String(20), nullable=False),
            sa.Column("call_id", sa.String(128), nullable=False),
            sa.Column("agent", sa.String(40), nullable=False),
            sa.Column("tool", sa.String(80)),
            sa.Column("summary", sa.String(500), nullable=False),
            sa.Column("credits", sa.Float(), nullable=False),
            sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
            sa.UniqueConstraint("run_id", "delegation_id", "step", "kind", "call_id", name="uq_agent_step_receipt"),
            sa.CheckConstraint("step >= 0 AND credits >= 0", name="ck_agent_step_nonnegative"),
        )
        op.create_index("ix_agent_steps_run_id", "agent_steps", ["run_id"])
    if not sa.inspect(bind).has_table("agent_workspace_items"):
        op.create_table(
            "agent_workspace_items",
            sa.Column("id", sa.Integer(), primary_key=True),
            sa.Column("run_id", sa.String(80), sa.ForeignKey("agent_runs.run_id"), nullable=False),
            sa.Column("key", sa.String(120), nullable=False),
            sa.Column("version", sa.Integer(), nullable=False),
            sa.Column("kind", sa.String(40), nullable=False),
            sa.Column("payload", sa.JSON(), nullable=False),
            sa.Column("artifact_ids", sa.JSON(), nullable=False),
            sa.Column("author_agent", sa.String(40), nullable=False),
            sa.Column("delegation_id", sa.Integer(), sa.ForeignKey("agent_delegations.id"), nullable=False),
            sa.Column("request_key", sa.String(128), nullable=False),
            sa.Column("inputs_hash", sa.String(64), nullable=False),
            sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
            sa.UniqueConstraint("run_id", "key", "version", name="uq_agent_workspace_version"),
            sa.UniqueConstraint("run_id", "request_key", name="uq_agent_workspace_request"),
            sa.CheckConstraint("version >= 1", name="ck_agent_workspace_version_positive"),
        )
        op.create_index("ix_agent_workspace_items_run_id", "agent_workspace_items", ["run_id"])


def downgrade():
    for name in ("agent_workspace_items", "agent_steps", "agent_delegations"):
        if sa.inspect(op.get_bind()).has_table(name):
            op.drop_table(name)
