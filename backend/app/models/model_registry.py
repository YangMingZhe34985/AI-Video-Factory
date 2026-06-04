from app.extensions import db
from app.models.base import SerializerMixin
from app.utils.time_utils import utc_now


class ModelRegistry(db.Model, SerializerMixin):
    __tablename__ = "models"

    id = db.Column(db.Integer, primary_key=True)
    model_id = db.Column(db.String(120), unique=True, nullable=False)
    display_name = db.Column(db.String(255), nullable=False)
    provider = db.Column(db.String(80), nullable=False)
    task_type = db.Column(db.String(80), nullable=False, index=True)
    adapter_name = db.Column(db.String(120), nullable=False)
    enabled = db.Column(db.Boolean, nullable=False, default=True)
    input_schema = db.Column(db.JSON, nullable=False, default=dict)
    parameter_schema = db.Column(db.JSON, nullable=False, default=dict)
    output_schema = db.Column(db.JSON, nullable=False, default=dict)
    default_params = db.Column(db.JSON, nullable=False, default=dict)
    created_at = db.Column(db.DateTime(timezone=True), nullable=False, default=utc_now)
    updated_at = db.Column(
        db.DateTime(timezone=True), nullable=False, default=utc_now, onupdate=utc_now
    )

    def to_dict(self) -> dict:
        data = super().to_dict()
        data["name"] = self.display_name
        data["model_key"] = self.model_id
        return data
