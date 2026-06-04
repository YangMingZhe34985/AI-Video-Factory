from app.extensions import db
from app.models.base import SerializerMixin
from app.utils.ids import new_id
from app.utils.time_utils import utc_now


class Template(db.Model, SerializerMixin):
    __tablename__ = "templates"

    id = db.Column(db.Integer, primary_key=True)
    template_id = db.Column(
        db.String(64), unique=True, nullable=False, default=lambda: new_id("tpl")
    )
    name = db.Column(db.String(255), nullable=False)
    series = db.Column(db.String(128), nullable=True)
    description = db.Column(db.Text)
    config = db.Column(db.JSON, nullable=False, default=dict)
    created_at = db.Column(db.DateTime(timezone=True), nullable=False, default=utc_now)
    updated_at = db.Column(
        db.DateTime(timezone=True), nullable=False, default=utc_now, onupdate=utc_now
    )

    jobs = db.relationship("Job", back_populates="template", lazy=True)
    prompts = db.relationship("PromptVersion", back_populates="template", lazy=True)
