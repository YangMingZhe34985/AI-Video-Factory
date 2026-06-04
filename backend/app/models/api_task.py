from app.extensions import db
from app.models.base import SerializerMixin
from app.utils.ids import new_id
from app.utils.time_utils import utc_now


class ApiTask(db.Model, SerializerMixin):
    __tablename__ = "api_tasks"

    id = db.Column(db.Integer, primary_key=True)
    api_task_id = db.Column(
        db.String(80), unique=True, nullable=False, default=lambda: new_id("api")
    )
    job_id = db.Column(db.Integer, db.ForeignKey("jobs.id"), nullable=False, index=True)
    node_run_id = db.Column(db.Integer, db.ForeignKey("job_node_runs.id"))
    branch_key = db.Column(db.String(80), nullable=False)
    model_id = db.Column(db.String(120), nullable=False)
    provider_task_id = db.Column(db.String(255), index=True)
    adapter_name = db.Column(db.String(120), nullable=False)
    status = db.Column(db.String(40), nullable=False, default="submitted")
    request_payload = db.Column(db.JSON, nullable=False, default=dict)
    response_payload = db.Column(db.JSON, nullable=False, default=dict)
    error_message = db.Column(db.Text)
    expected_artifact_path = db.Column(db.String(1024))
    submitted_at = db.Column(db.DateTime(timezone=True))
    completed_at = db.Column(db.DateTime(timezone=True))
    created_at = db.Column(db.DateTime(timezone=True), nullable=False, default=utc_now)
    updated_at = db.Column(
        db.DateTime(timezone=True), nullable=False, default=utc_now, onupdate=utc_now
    )

    job = db.relationship("Job", back_populates="api_tasks")
    node_run = db.relationship("JobNodeRun", back_populates="api_tasks")
    artifacts = db.relationship("Artifact", back_populates="api_task", lazy=True)
