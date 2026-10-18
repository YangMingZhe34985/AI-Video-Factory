from app.extensions import db
from app.models.base import SerializerMixin
from app.utils.ids import new_id
from app.utils.time_utils import utc_now


class ToolInvocation(db.Model, SerializerMixin):
    """Ledger of skill-layer tool calls: idempotency, budget and job linkage."""

    __tablename__ = "tool_invocations"

    id = db.Column(db.Integer, primary_key=True)
    invocation_id = db.Column(
        db.String(80), unique=True, nullable=False, default=lambda: new_id("tinv")
    )
    tool_name = db.Column(db.String(80), nullable=False, index=True)
    idempotency_key = db.Column(db.String(128), unique=True, nullable=False)
    caller_role = db.Column(db.String(40), nullable=False)
    caller_agent = db.Column(db.String(40), nullable=True)
    delegation_id = db.Column(db.Integer, nullable=True)
    budget_scope = db.Column(db.String(128), nullable=False, default="default", index=True)
    status = db.Column(db.String(40), nullable=False, default="pending")
    attempt = db.Column(db.Integer, nullable=False, default=1)
    input_payload = db.Column(db.JSON, nullable=False, default=dict)
    output_payload = db.Column(db.JSON, nullable=False, default=dict)
    error_code = db.Column(db.String(80))
    error_message = db.Column(db.Text)
    # SET NULL keeps the ledger (and its budget accounting) when a job is deleted.
    job_id = db.Column(
        db.Integer, db.ForeignKey("jobs.id", ondelete="SET NULL"), nullable=True, index=True
    )
    estimated_cost = db.Column(db.Float, nullable=False, default=0.0)
    duration_ms = db.Column(db.Integer)
    # Start of the latest attempt; job states written before it are stale.
    started_at = db.Column(db.DateTime(timezone=True))
    finished_at = db.Column(db.DateTime(timezone=True))
    created_at = db.Column(db.DateTime(timezone=True), nullable=False, default=utc_now)
    updated_at = db.Column(
        db.DateTime(timezone=True), nullable=False, default=utc_now, onupdate=utc_now
    )

    job = db.relationship("Job")
