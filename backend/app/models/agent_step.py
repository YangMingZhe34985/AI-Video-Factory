"""Public-safe execution summaries; raw conversation remains private state."""

from app.extensions import db
from app.models.base import SerializerMixin
from app.utils.time_utils import utc_now


class AgentStep(db.Model, SerializerMixin):
    __tablename__ = "agent_steps"

    id = db.Column(db.Integer, primary_key=True)
    run_id = db.Column(db.String(80), db.ForeignKey("agent_runs.run_id"), nullable=False, index=True)
    delegation_id = db.Column(db.Integer, db.ForeignKey("agent_delegations.id"), nullable=False)
    step = db.Column(db.Integer, nullable=False)
    kind = db.Column(db.String(20), nullable=False)
    call_id = db.Column(db.String(128), nullable=False, default="")
    agent = db.Column(db.String(40), nullable=False)
    tool = db.Column(db.String(80))
    summary = db.Column(db.String(500), nullable=False)
    credits = db.Column(db.Float, nullable=False, default=0)
    created_at = db.Column(db.DateTime(timezone=True), nullable=False, default=utc_now)

    __table_args__ = (
        db.UniqueConstraint("run_id", "delegation_id", "step", "kind", "call_id", name="uq_agent_step_receipt"),
        db.CheckConstraint("step >= 0 AND credits >= 0", name="ck_agent_step_nonnegative"),
    )
