from copy import deepcopy

from app.extensions import db
from app.models.base import SerializerMixin
from app.utils.time_utils import utc_now


class AgentShotTask(db.Model, SerializerMixin):
    """Durable preview attempts; previous outputs remain available for rollback."""

    __tablename__ = "agent_shot_tasks"

    id = db.Column(db.Integer, primary_key=True)
    run_id = db.Column(db.String(80), nullable=False, index=True)
    plan_version = db.Column(db.Integer, nullable=False)
    target_type = db.Column(db.String(20), nullable=False)
    target_id = db.Column(db.String(80), nullable=False)
    attempt = db.Column(db.Integer, nullable=False, default=1)
    status = db.Column(db.String(20), nullable=False, default="pending", index=True)
    inputs_hash = db.Column(db.String(64), nullable=False)
    invocation_id = db.Column(db.String(80), db.ForeignKey("tool_invocations.invocation_id", ondelete="SET NULL"))
    job_id = db.Column(db.String(80), db.ForeignKey("jobs.job_id", ondelete="SET NULL"))
    artifact_ids = db.Column(db.JSON, nullable=False, default=list)
    estimated_cost = db.Column(db.Float, nullable=False, default=0.0)
    error = db.Column(db.JSON(none_as_null=True))
    created_at = db.Column(db.DateTime(timezone=True), nullable=False, default=utc_now)
    updated_at = db.Column(db.DateTime(timezone=True), nullable=False, default=utc_now, onupdate=utc_now)

    __table_args__ = (
        db.ForeignKeyConstraint(["run_id", "plan_version"],
                                ["agent_plan_versions.run_id", "agent_plan_versions.version"]),
        db.UniqueConstraint("run_id", "plan_version", "target_type", "target_id", "attempt",
                            name="uq_agent_shot_attempt"),
        db.CheckConstraint("attempt >= 1", name="ck_agent_shot_attempt_positive"),
    )

    def to_dict(self):
        return deepcopy(super().to_dict())
