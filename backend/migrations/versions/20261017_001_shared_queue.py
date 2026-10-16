"""Shared execution queue, transactional outbox and resumable provider tasks."""
from alembic import op
import sqlalchemy as sa

revision = "20261017_001"
down_revision = "20261016_001"
branch_labels = None
depends_on = None


def upgrade():
    node_columns = {column["name"] for column in sa.inspect(op.get_bind()).get_columns("job_node_runs")}
    if "execution_key" not in node_columns:
        with op.batch_alter_table("job_node_runs") as batch:
            batch.add_column(sa.Column("execution_key", sa.String(220)))
            batch.create_unique_constraint("uq_node_execution_key", ["execution_key"])
    existing = {column["name"] for column in sa.inspect(op.get_bind()).get_columns("api_tasks")}
    columns = [
        sa.Column("operation_key", sa.String(100)),
        sa.Column("queue_phase", sa.String(24)),
        sa.Column("queue_generation", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("queue_data", sa.JSON()),
        sa.Column("next_poll_at", sa.DateTime(timezone=True)),
        sa.Column("lease_token", sa.String(80)),
        sa.Column("lease_until", sa.DateTime(timezone=True)),
        sa.Column("queue_attempts", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("poll_count", sa.Integer(), nullable=False, server_default="0"),
    ]
    with op.batch_alter_table("api_tasks") as batch:
        for column in columns:
            if column.name not in existing:
                batch.add_column(column)
        if "operation_key" not in existing:
            batch.create_unique_constraint("uq_api_tasks_operation_key", ["operation_key"])
            batch.create_index("ix_api_tasks_queue_phase", ["queue_phase"])
            batch.create_index("ix_api_tasks_next_poll_at", ["next_poll_at"])
    # These tables contain no environment-dependent defaults or seeds.
    from app.models.queue import JobDispatch, TaskOutbox
    JobDispatch.__table__.create(bind=op.get_bind(), checkfirst=True)
    TaskOutbox.__table__.create(bind=op.get_bind(), checkfirst=True)


def downgrade():
    op.drop_table("task_outbox")
    op.drop_table("job_dispatches")
    with op.batch_alter_table("job_node_runs") as batch:
        batch.drop_constraint("uq_node_execution_key", type_="unique")
        batch.drop_column("execution_key")
    with op.batch_alter_table("api_tasks") as batch:
        batch.drop_index("ix_api_tasks_next_poll_at")
        batch.drop_index("ix_api_tasks_queue_phase")
        batch.drop_constraint("uq_api_tasks_operation_key", type_="unique")
        for name in ("operation_key", "queue_phase", "queue_generation", "queue_data", "next_poll_at",
                     "lease_token", "lease_until", "queue_attempts", "poll_count"):
            batch.drop_column(name)
