from app.extensions import db
from app.models.base import SerializerMixin
from app.utils.ids import new_id
from app.utils.time_utils import utc_now


class AgentRun(db.Model, SerializerMixin):
    """Business index and durable command inbox; graph checkpoints own execution state."""

    __tablename__ = "agent_runs"

    id = db.Column(db.Integer, primary_key=True)
    run_id = db.Column(db.String(80), unique=True, nullable=False, default=lambda: new_id("agent"))
    owner_id = db.Column(db.String(80), nullable=False, index=True)
    request_key = db.Column(db.String(128), nullable=False)
    request = db.Column(db.JSON, nullable=False)
    status = db.Column(db.String(40), nullable=False, default="queued", index=True)
    snapshot = db.Column(db.JSON, nullable=False, default=dict)
    command = db.Column(db.JSON(none_as_null=True), nullable=True)
    error = db.Column(db.JSON, nullable=True)
    resume_count = db.Column(db.Integer, nullable=False, default=0)
    created_at = db.Column(db.DateTime(timezone=True), nullable=False, default=utc_now)
    updated_at = db.Column(db.DateTime(timezone=True), nullable=False, default=utc_now, onupdate=utc_now)

    __table_args__ = (db.UniqueConstraint("owner_id", "request_key", name="uq_agent_owner_request"),)
