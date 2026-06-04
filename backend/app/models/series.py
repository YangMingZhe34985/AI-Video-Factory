from app.extensions import db
from app.models.base import SerializerMixin
from app.utils.time_utils import utc_now


class Series(db.Model, SerializerMixin):
    __tablename__ = "series"

    id = db.Column(db.Integer, primary_key=True)
    series_id = db.Column(db.String(128), unique=True, nullable=False)
    name = db.Column(db.String(255), nullable=False)
    description = db.Column(db.Text, nullable=True)
    is_default = db.Column(db.Boolean, nullable=False, default=False)
    created_at = db.Column(db.DateTime(timezone=True), nullable=False, default=utc_now)
    updated_at = db.Column(
        db.DateTime(timezone=True), nullable=False, default=utc_now, onupdate=utc_now
    )

    def to_dict(self) -> dict:
        data = super().to_dict()
        return data
