"""Initial schema with Job-scoped prompt versions.

Revision ID: 20260602_001
Revises:
Create Date: 2026-06-02
"""

from alembic import op
import sqlalchemy as sa


revision = "20260602_001"
down_revision = None
branch_labels = None
depends_on = None


def upgrade():
    op.create_table(
        "series",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("series_id", sa.String(length=128), nullable=False),
        sa.Column("name", sa.String(length=255), nullable=False),
        sa.Column("description", sa.Text(), nullable=True),
        sa.Column("is_default", sa.Boolean(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("series_id"),
    )

    op.create_table(
        "templates",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("template_id", sa.String(length=64), nullable=False),
        sa.Column("name", sa.String(length=255), nullable=False),
        sa.Column("series", sa.String(length=128), nullable=True),
        sa.Column("description", sa.Text(), nullable=True),
        sa.Column("config", sa.JSON(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("template_id"),
    )

    op.create_table(
        "users",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("user_id", sa.String(length=64), nullable=False),
        sa.Column("username", sa.String(length=120), nullable=False),
        sa.Column("email", sa.String(length=255), nullable=True),
        sa.Column("password_hash", sa.String(length=255), nullable=False),
        sa.Column("is_active", sa.Boolean(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("email"),
        sa.UniqueConstraint("user_id"),
    )

    op.create_table(
        "models",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("model_id", sa.String(length=120), nullable=False),
        sa.Column("display_name", sa.String(length=255), nullable=False),
        sa.Column("provider", sa.String(length=80), nullable=False),
        sa.Column("task_type", sa.String(length=80), nullable=False),
        sa.Column("adapter_name", sa.String(length=120), nullable=False),
        sa.Column("enabled", sa.Boolean(), nullable=False),
        sa.Column("input_schema", sa.JSON(), nullable=False),
        sa.Column("parameter_schema", sa.JSON(), nullable=False),
        sa.Column("output_schema", sa.JSON(), nullable=False),
        sa.Column("default_params", sa.JSON(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("model_id"),
    )
    op.create_index(op.f("ix_models_task_type"), "models", ["task_type"], unique=False)

    op.create_table(
        "jobs",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("job_id", sa.String(length=80), nullable=False),
        sa.Column("template_id", sa.Integer(), nullable=False),
        sa.Column("source_video_path", sa.String(length=1024), nullable=True),
        sa.Column("source_file_name", sa.String(length=255), nullable=True),
        sa.Column("source_hash", sa.String(length=128), nullable=True),
        sa.Column("status", sa.String(length=40), nullable=False),
        sa.Column("current_node", sa.String(length=120), nullable=True),
        sa.Column("strategy", sa.String(length=80), nullable=False),
        sa.Column("budget_limit", sa.Numeric(precision=12, scale=4), nullable=True),
        sa.Column("cost_used", sa.Numeric(precision=12, scale=4), nullable=False),
        sa.Column("node_overrides", sa.JSON(), nullable=False),
        sa.Column("config", sa.JSON(), nullable=False),
        sa.Column("error_summary", sa.Text(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(["template_id"], ["templates.id"]),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("job_id"),
    )
    op.create_index(op.f("ix_jobs_status"), "jobs", ["status"], unique=False)

    op.create_table(
        "workflow_nodes",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("template_id", sa.Integer(), nullable=True),
        sa.Column("node_key", sa.String(length=120), nullable=False),
        sa.Column("display_name", sa.String(length=255), nullable=False),
        sa.Column("sequence", sa.Integer(), nullable=False),
        sa.Column("branch_key", sa.String(length=80), nullable=False),
        sa.Column("enabled", sa.Boolean(), nullable=False),
        sa.Column("depends_on", sa.JSON(), nullable=False),
        sa.Column("config", sa.JSON(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(["template_id"], ["templates.id"]),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("template_id", "node_key", name="uq_workflow_node_template_key"),
    )
    op.create_index(op.f("ix_workflow_nodes_node_key"), "workflow_nodes", ["node_key"], unique=False)
    op.create_index(op.f("ix_workflow_nodes_sequence"), "workflow_nodes", ["sequence"], unique=False)

    op.create_table(
        "prompt_versions",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("prompt_id", sa.String(length=80), nullable=False),
        sa.Column("template_id", sa.Integer(), nullable=False),
        sa.Column("job_id", sa.Integer(), nullable=True),
        sa.Column("prompt_type", sa.String(length=120), nullable=False),
        sa.Column("prompt_key", sa.String(length=120), nullable=False),
        sa.Column("version", sa.String(length=40), nullable=False),
        sa.Column("title", sa.String(length=255), nullable=False),
        sa.Column("content", sa.Text(), nullable=False),
        sa.Column("content_format", sa.String(length=40), nullable=False),
        sa.Column("is_active", sa.Boolean(), nullable=False),
        sa.Column("source", sa.String(length=80), nullable=False),
        sa.Column("parent_version", sa.String(length=40), nullable=True),
        sa.Column("note", sa.Text(), nullable=True),
        sa.Column("created_by", sa.String(length=120), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(["job_id"], ["jobs.id"]),
        sa.ForeignKeyConstraint(["template_id"], ["templates.id"]),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("job_id", "prompt_type", "prompt_key", "version", name="uq_prompt_job_type_key_version"),
        sa.UniqueConstraint("prompt_id"),
    )
    op.create_index(op.f("ix_prompt_versions_prompt_key"), "prompt_versions", ["prompt_key"], unique=False)
    op.create_index(op.f("ix_prompt_versions_prompt_type"), "prompt_versions", ["prompt_type"], unique=False)

    op.create_table(
        "job_node_runs",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("run_id", sa.String(length=80), nullable=False),
        sa.Column("job_id", sa.Integer(), nullable=False),
        sa.Column("node_key", sa.String(length=120), nullable=False),
        sa.Column("status", sa.String(length=40), nullable=False),
        sa.Column("attempt", sa.Integer(), nullable=False),
        sa.Column("force", sa.Boolean(), nullable=False),
        sa.Column("input_snapshot", sa.JSON(), nullable=False),
        sa.Column("output_snapshot", sa.JSON(), nullable=False),
        sa.Column("error_message", sa.Text(), nullable=True),
        sa.Column("log_path", sa.String(length=1024), nullable=True),
        sa.Column("started_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("ended_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(["job_id"], ["jobs.id"]),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("run_id"),
    )
    op.create_index(op.f("ix_job_node_runs_job_id"), "job_node_runs", ["job_id"], unique=False)
    op.create_index(op.f("ix_job_node_runs_node_key"), "job_node_runs", ["node_key"], unique=False)

    op.create_table(
        "api_tasks",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("api_task_id", sa.String(length=80), nullable=False),
        sa.Column("job_id", sa.Integer(), nullable=False),
        sa.Column("node_run_id", sa.Integer(), nullable=True),
        sa.Column("branch_key", sa.String(length=80), nullable=False),
        sa.Column("model_id", sa.String(length=120), nullable=False),
        sa.Column("provider_task_id", sa.String(length=255), nullable=True),
        sa.Column("adapter_name", sa.String(length=120), nullable=False),
        sa.Column("status", sa.String(length=40), nullable=False),
        sa.Column("request_payload", sa.JSON(), nullable=False),
        sa.Column("response_payload", sa.JSON(), nullable=False),
        sa.Column("error_message", sa.Text(), nullable=True),
        sa.Column("expected_artifact_path", sa.String(length=1024), nullable=True),
        sa.Column("submitted_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("completed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(["job_id"], ["jobs.id"]),
        sa.ForeignKeyConstraint(["node_run_id"], ["job_node_runs.id"]),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("api_task_id"),
    )
    op.create_index(op.f("ix_api_tasks_job_id"), "api_tasks", ["job_id"], unique=False)
    op.create_index(op.f("ix_api_tasks_provider_task_id"), "api_tasks", ["provider_task_id"], unique=False)

    op.create_table(
        "artifacts",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("artifact_id", sa.String(length=80), nullable=False),
        sa.Column("job_id", sa.Integer(), nullable=False),
        sa.Column("node_run_id", sa.Integer(), nullable=True),
        sa.Column("api_task_id", sa.Integer(), nullable=True),
        sa.Column("file_path", sa.String(length=1024), nullable=False),
        sa.Column("file_name", sa.String(length=255), nullable=False),
        sa.Column("mime_type", sa.String(length=160), nullable=False),
        sa.Column("size", sa.BigInteger(), nullable=False),
        sa.Column("artifact_type", sa.String(length=80), nullable=False),
        sa.Column("branch_key", sa.String(length=80), nullable=True),
        sa.Column("model_id", sa.String(length=120), nullable=True),
        sa.Column("prompt_version", sa.String(length=40), nullable=True),
        sa.Column("metadata", sa.JSON(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(["api_task_id"], ["api_tasks.id"]),
        sa.ForeignKeyConstraint(["job_id"], ["jobs.id"]),
        sa.ForeignKeyConstraint(["node_run_id"], ["job_node_runs.id"]),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("artifact_id"),
    )
    op.create_index(op.f("ix_artifacts_artifact_type"), "artifacts", ["artifact_type"], unique=False)
    op.create_index(op.f("ix_artifacts_job_id"), "artifacts", ["job_id"], unique=False)

    op.create_table(
        "job_events",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("event_id", sa.String(length=80), nullable=False),
        sa.Column("job_id", sa.Integer(), nullable=False),
        sa.Column("event_type", sa.String(length=120), nullable=False),
        sa.Column("node_key", sa.String(length=120), nullable=True),
        sa.Column("message", sa.String(length=500), nullable=True),
        sa.Column("payload", sa.JSON(), nullable=False),
        sa.Column("level", sa.String(length=20), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(["job_id"], ["jobs.id"]),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("event_id"),
    )
    op.create_index(op.f("ix_job_events_event_type"), "job_events", ["event_type"], unique=False)
    op.create_index(op.f("ix_job_events_job_id"), "job_events", ["job_id"], unique=False)

    op.create_table(
        "job_prompt_refs",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("ref_id", sa.String(length=80), nullable=False),
        sa.Column("job_id", sa.Integer(), nullable=False),
        sa.Column("prompt_version_id", sa.Integer(), nullable=False),
        sa.Column("prompt_type", sa.String(length=120), nullable=False),
        sa.Column("prompt_key", sa.String(length=120), nullable=False),
        sa.Column("version", sa.String(length=40), nullable=False),
        sa.Column("title", sa.String(length=255), nullable=True),
        sa.Column("content_snapshot", sa.Text(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(["job_id"], ["jobs.id"]),
        sa.ForeignKeyConstraint(["prompt_version_id"], ["prompt_versions.id"]),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("job_id", "prompt_type", "prompt_key", "version", name="uq_job_prompt_type_key_version"),
        sa.UniqueConstraint("ref_id"),
    )
    op.create_index(op.f("ix_job_prompt_refs_job_id"), "job_prompt_refs", ["job_id"], unique=False)


def downgrade():
    op.drop_index(op.f("ix_job_prompt_refs_job_id"), table_name="job_prompt_refs")
    op.drop_table("job_prompt_refs")
    op.drop_index(op.f("ix_job_events_job_id"), table_name="job_events")
    op.drop_index(op.f("ix_job_events_event_type"), table_name="job_events")
    op.drop_table("job_events")
    op.drop_index(op.f("ix_artifacts_job_id"), table_name="artifacts")
    op.drop_index(op.f("ix_artifacts_artifact_type"), table_name="artifacts")
    op.drop_table("artifacts")
    op.drop_index(op.f("ix_api_tasks_provider_task_id"), table_name="api_tasks")
    op.drop_index(op.f("ix_api_tasks_job_id"), table_name="api_tasks")
    op.drop_table("api_tasks")
    op.drop_index(op.f("ix_job_node_runs_node_key"), table_name="job_node_runs")
    op.drop_index(op.f("ix_job_node_runs_job_id"), table_name="job_node_runs")
    op.drop_table("job_node_runs")
    op.drop_index(op.f("ix_prompt_versions_prompt_type"), table_name="prompt_versions")
    op.drop_index(op.f("ix_prompt_versions_prompt_key"), table_name="prompt_versions")
    op.drop_table("prompt_versions")
    op.drop_index(op.f("ix_workflow_nodes_sequence"), table_name="workflow_nodes")
    op.drop_index(op.f("ix_workflow_nodes_node_key"), table_name="workflow_nodes")
    op.drop_table("workflow_nodes")
    op.drop_index(op.f("ix_jobs_status"), table_name="jobs")
    op.drop_table("jobs")
    op.drop_index(op.f("ix_models_task_type"), table_name="models")
    op.drop_table("models")
    op.drop_table("users")
    op.drop_table("templates")
    op.drop_table("series")
