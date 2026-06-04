from app.extensions import db
from app.models.base import SerializerMixin
from app.utils.ids import new_id
from app.utils.time_utils import utc_now


class JobPromptRef(db.Model, SerializerMixin):
    __tablename__ = "job_prompt_refs"
    __table_args__ = (
        db.UniqueConstraint(
            "job_id",
            "prompt_type",
            "prompt_key",
            "version",
            name="uq_job_prompt_type_key_version",
        ),
    )

    id = db.Column(db.Integer, primary_key=True)
    ref_id = db.Column(
        db.String(80), unique=True, nullable=False, default=lambda: new_id("jpr")
    )
    job_id = db.Column(db.Integer, db.ForeignKey("jobs.id"), nullable=False, index=True)
    prompt_version_id = db.Column(
        db.Integer, db.ForeignKey("prompt_versions.id"), nullable=False
    )
    prompt_type = db.Column(db.String(120), nullable=False)
    prompt_key = db.Column(db.String(120), nullable=False, default="default")
    version = db.Column(db.String(40), nullable=False)
    title = db.Column(db.String(255))
    content_snapshot = db.Column(db.Text, nullable=False)
    created_at = db.Column(db.DateTime(timezone=True), nullable=False, default=utc_now)

    job = db.relationship("Job", back_populates="prompt_refs")
    prompt_version = db.relationship("PromptVersion")
