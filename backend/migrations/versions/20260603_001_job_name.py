"""Add optional Job display name.

Revision ID: 20260603_001
Revises: 20260602_001
Create Date: 2026-06-03
"""

from alembic import op
import sqlalchemy as sa


revision = "20260603_001"
down_revision = "20260602_001"
branch_labels = None
depends_on = None


def upgrade():
    with op.batch_alter_table("jobs") as batch_op:
        batch_op.add_column(sa.Column("job_name", sa.String(length=255), nullable=True))
        batch_op.create_unique_constraint(
            "uq_jobs_template_job_name",
            ["template_id", "job_name"],
        )


def downgrade():
    with op.batch_alter_table("jobs") as batch_op:
        batch_op.drop_constraint("uq_jobs_template_job_name", type_="unique")
        batch_op.drop_column("job_name")
