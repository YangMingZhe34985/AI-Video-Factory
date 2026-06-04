from app.extensions import db
from app.models.base import SerializerMixin
from app.utils.ids import new_id
from app.utils.time_utils import utc_now


class Artifact(db.Model, SerializerMixin):
    __tablename__ = "artifacts"

    id = db.Column(db.Integer, primary_key=True)
    artifact_id = db.Column(
        db.String(80), unique=True, nullable=False, default=lambda: new_id("art")
    )
    job_id = db.Column(db.Integer, db.ForeignKey("jobs.id"), nullable=False, index=True)
    node_run_id = db.Column(db.Integer, db.ForeignKey("job_node_runs.id"))
    api_task_id = db.Column(db.Integer, db.ForeignKey("api_tasks.id"))
    file_path = db.Column(db.String(1024), nullable=False)
    file_name = db.Column(db.String(255), nullable=False)
    mime_type = db.Column(db.String(160), nullable=False, default="application/octet-stream")
    size = db.Column(db.BigInteger, nullable=False, default=0)
    artifact_type = db.Column(db.String(80), nullable=False, index=True)
    branch_key = db.Column(db.String(80))
    model_id = db.Column(db.String(120))
    prompt_version = db.Column(db.String(40))
    meta = db.Column("metadata", db.JSON, nullable=False, default=dict)
    created_at = db.Column(db.DateTime(timezone=True), nullable=False, default=utc_now)

    job = db.relationship("Job", back_populates="artifacts")
    node_run = db.relationship("JobNodeRun", back_populates="artifacts")
    api_task = db.relationship("ApiTask", back_populates="artifacts")

    def to_dict(self) -> dict:
        data = super().to_dict()
        data["filename"] = self.file_name
        data["name"] = self.file_name
        return data
