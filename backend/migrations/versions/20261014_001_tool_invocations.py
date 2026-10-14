"""Add the skill-layer tool invocation ledger.

Revision ID: 20261014_001
Revises: 20260603_001
Create Date: 2026-10-14
"""

from alembic import op
import sqlalchemy as sa


revision = "20261014_001"
down_revision = "20260603_001"
branch_labels = None
depends_on = None


def upgrade():
    # `flask db upgrade` boots the app first, and SchemaService may already
    # have created this table for databases without Alembic history.
    if sa.inspect(op.get_bind()).has_table("tool_invocations"):
        return
    op.create_table(
        "tool_invocations",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("invocation_id", sa.String(length=80), nullable=False),
        sa.Column("tool_name", sa.String(length=80), nullable=False),
        sa.Column("idempotency_key", sa.String(length=128), nullable=False),
        sa.Column("caller_role", sa.String(length=40), nullable=False),
        sa.Column("budget_scope", sa.String(length=128), nullable=False),
        sa.Column("status", sa.String(length=40), nullable=False),
        sa.Column("attempt", sa.Integer(), nullable=False),
        sa.Column("input_payload", sa.JSON(), nullable=False),
        sa.Column("output_payload", sa.JSON(), nullable=False),
        sa.Column("error_code", sa.String(length=80), nullable=True),
        sa.Column("error_message", sa.Text(), nullable=True),
        sa.Column("job_id", sa.Integer(), nullable=True),
        sa.Column("estimated_cost", sa.Float(), nullable=False),
        sa.Column("duration_ms", sa.Integer(), nullable=True),
        sa.Column("started_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("finished_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(["job_id"], ["jobs.id"], ondelete="SET NULL"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("invocation_id"),
        sa.UniqueConstraint("idempotency_key"),
    )
    op.create_index("ix_tool_invocations_tool_name", "tool_invocations", ["tool_name"])
    op.create_index("ix_tool_invocations_budget_scope", "tool_invocations", ["budget_scope"])
    op.create_index("ix_tool_invocations_job_id", "tool_invocations", ["job_id"])


def downgrade():
    op.drop_index("ix_tool_invocations_job_id", table_name="tool_invocations")
    op.drop_index("ix_tool_invocations_budget_scope", table_name="tool_invocations")
    op.drop_index("ix_tool_invocations_tool_name", table_name="tool_invocations")
    op.drop_table("tool_invocations")
