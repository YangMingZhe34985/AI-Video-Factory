from app.extensions import db
from app.models.base import SerializerMixin
from app.utils.ids import new_id
from app.utils.time_utils import utc_now


class Job(db.Model, SerializerMixin):
    __tablename__ = "jobs"
    __table_args__ = (
        db.UniqueConstraint("template_id", "job_name", name="uq_jobs_template_job_name"),
    )

    id = db.Column(db.Integer, primary_key=True)
    job_id = db.Column(
        db.String(80), unique=True, nullable=False, default=lambda: new_id("job")
    )
    job_name = db.Column(db.String(255), nullable=True)
    template_id = db.Column(db.Integer, db.ForeignKey("templates.id"), nullable=False)
    source_video_path = db.Column(db.String(1024))
    source_file_name = db.Column(db.String(255))
    source_hash = db.Column(db.String(128))
    status = db.Column(db.String(40), nullable=False, default="pending", index=True)
    current_node = db.Column(db.String(120))
    strategy = db.Column(db.String(80), nullable=False, default="default")
    budget_limit = db.Column(db.Numeric(12, 4))
    cost_used = db.Column(db.Numeric(12, 4), nullable=False, default=0)
    node_overrides = db.Column(db.JSON, nullable=False, default=dict)
    config = db.Column(db.JSON, nullable=False, default=dict)
    error_summary = db.Column(db.Text)
    created_at = db.Column(db.DateTime(timezone=True), nullable=False, default=utc_now)
    updated_at = db.Column(
        db.DateTime(timezone=True), nullable=False, default=utc_now, onupdate=utc_now
    )

    template = db.relationship("Template", back_populates="jobs")
    node_runs = db.relationship(
        "JobNodeRun", back_populates="job", lazy=True, cascade="all, delete-orphan"
    )
    api_tasks = db.relationship(
        "ApiTask", back_populates="job", lazy=True, cascade="all, delete-orphan"
    )
    artifacts = db.relationship(
        "Artifact", back_populates="job", lazy=True, cascade="all, delete-orphan"
    )
    events = db.relationship(
        "JobEvent", back_populates="job", lazy=True, cascade="all, delete-orphan"
    )
    prompt_refs = db.relationship(
        "JobPromptRef", back_populates="job", lazy=True, cascade="all, delete-orphan"
    )
    prompt_versions = db.relationship(
        "PromptVersion", back_populates="job", lazy=True, cascade="all, delete-orphan"
    )

    @property
    def external_template_id(self) -> str | None:
        return self.template.template_id if self.template else None

    def to_dict(self) -> dict:
        data = super().to_dict()
        data["template_id"] = self.external_template_id
        return data
