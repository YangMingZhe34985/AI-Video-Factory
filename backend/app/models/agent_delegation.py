"""Durable, quota-bearing Agent v3 delegation instances."""

from app.extensions import db
from app.models.base import SerializerMixin
from app.utils.time_utils import utc_now


class AgentDelegation(db.Model, SerializerMixin):
    __tablename__ = "agent_delegations"

    id = db.Column(db.Integer, primary_key=True)
    run_id = db.Column(db.String(80), db.ForeignKey("agent_runs.run_id"), nullable=False, index=True)
    parent_id = db.Column(db.Integer, db.ForeignKey("agent_delegations.id"))
    agent = db.Column(db.String(40), nullable=False)
    status = db.Column(db.String(40), nullable=False, default="pending", index=True)
    task = db.Column(db.Text, nullable=False)
    context_refs = db.Column(db.JSON, nullable=False, default=list)
    expected = db.Column(db.String(1000), nullable=False, default="")
    depth = db.Column(db.Integer, nullable=False, default=0)
    credits_limit = db.Column(db.Float, nullable=False, default=0)
    steps = db.Column(db.Integer, nullable=False, default=0)
    llm_calls = db.Column(db.Integer, nullable=False, default=0)
    output = db.Column(db.JSON(none_as_null=True))
    error = db.Column(db.JSON(none_as_null=True))
    state = db.Column(db.JSON, nullable=False, default=dict)
    request_key = db.Column(db.String(128), nullable=False)
    started_at = db.Column(db.DateTime(timezone=True), nullable=False, default=utc_now)
    created_at = db.Column(db.DateTime(timezone=True), nullable=False, default=utc_now)
    updated_at = db.Column(db.DateTime(timezone=True), nullable=False, default=utc_now, onupdate=utc_now)

    __table_args__ = (
        db.UniqueConstraint("run_id", "request_key", name="uq_agent_delegation_request"),
        db.CheckConstraint("depth >= 0 AND credits_limit >= 0 AND steps >= 0 AND llm_calls >= 0",
                           name="ck_agent_delegation_limits"),
    )
