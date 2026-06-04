from app.extensions import db
from app.models.base import SerializerMixin
from app.utils.ids import new_id
from app.utils.time_utils import utc_now


class PromptVersion(db.Model, SerializerMixin):
    __tablename__ = "prompt_versions"
    __table_args__ = (
        db.UniqueConstraint(
            "job_id",
            "prompt_type",
            "prompt_key",
            "version",
            name="uq_prompt_job_type_key_version",
        ),
    )

    id = db.Column(db.Integer, primary_key=True)
    prompt_id = db.Column(
        db.String(80), unique=True, nullable=False, default=lambda: new_id("prompt")
    )
    template_id = db.Column(db.Integer, db.ForeignKey("templates.id"), nullable=False)
    job_id = db.Column(db.Integer, db.ForeignKey("jobs.id"), nullable=True)
    prompt_type = db.Column(db.String(120), nullable=False, index=True)
    prompt_key = db.Column(db.String(120), nullable=False, default="default", index=True)
    version = db.Column(db.String(40), nullable=False)
    title = db.Column(db.String(255), nullable=False)
    content = db.Column(db.Text, nullable=False)
    content_format = db.Column(db.String(40), nullable=False, default="markdown")
    is_active = db.Column(db.Boolean, nullable=False, default=True)
    source = db.Column(db.String(80), nullable=False, default="manual")
    parent_version = db.Column(db.String(40))
    note = db.Column(db.Text)
    created_by = db.Column(db.String(120))
    created_at = db.Column(db.DateTime(timezone=True), nullable=False, default=utc_now)
    updated_at = db.Column(
        db.DateTime(timezone=True), nullable=False, default=utc_now, onupdate=utc_now
    )

    template = db.relationship("Template", back_populates="prompts")
    job = db.relationship("Job", back_populates="prompt_versions", foreign_keys=[job_id])

    def to_dict(self) -> dict:
        data = super().to_dict()
        data["template_id"] = self.template.template_id if self.template else None
        data["job_id"] = self.job.job_id if self.job else None
        return data
