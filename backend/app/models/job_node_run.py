from app.extensions import db
from app.models.base import SerializerMixin
from app.utils.ids import new_id
from app.utils.time_utils import utc_now


class JobNodeRun(db.Model, SerializerMixin):
    __tablename__ = "job_node_runs"

    id = db.Column(db.Integer, primary_key=True)
    run_id = db.Column(
        db.String(80), unique=True, nullable=False, default=lambda: new_id("run")
    )
    job_id = db.Column(db.Integer, db.ForeignKey("jobs.id"), nullable=False, index=True)
    node_key = db.Column(db.String(120), nullable=False, index=True)
    status = db.Column(db.String(40), nullable=False, default="pending")
    attempt = db.Column(db.Integer, nullable=False, default=1)
    force = db.Column(db.Boolean, nullable=False, default=False)
    input_snapshot = db.Column(db.JSON, nullable=False, default=dict)
    output_snapshot = db.Column(db.JSON, nullable=False, default=dict)
    error_message = db.Column(db.Text)
    log_path = db.Column(db.String(1024))
    started_at = db.Column(db.DateTime(timezone=True))
    ended_at = db.Column(db.DateTime(timezone=True))
    created_at = db.Column(db.DateTime(timezone=True), nullable=False, default=utc_now)
    updated_at = db.Column(
        db.DateTime(timezone=True), nullable=False, default=utc_now, onupdate=utc_now
    )

    job = db.relationship("Job", back_populates="node_runs")
    api_tasks = db.relationship("ApiTask", back_populates="node_run", lazy=True)
    artifacts = db.relationship("Artifact", back_populates="node_run", lazy=True)
