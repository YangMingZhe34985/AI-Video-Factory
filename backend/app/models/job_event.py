from app.extensions import db
from app.models.base import SerializerMixin
from app.utils.ids import new_id
from app.utils.time_utils import utc_now


class JobEvent(db.Model, SerializerMixin):
    __tablename__ = "job_events"

    id = db.Column(db.Integer, primary_key=True)
    event_id = db.Column(
        db.String(80), unique=True, nullable=False, default=lambda: new_id("evt")
    )
    job_id = db.Column(db.Integer, db.ForeignKey("jobs.id"), nullable=False, index=True)
    event_type = db.Column(db.String(120), nullable=False, index=True)
    node_key = db.Column(db.String(120))
    message = db.Column(db.String(500))
    payload = db.Column(db.JSON, nullable=False, default=dict)
    level = db.Column(db.String(20), nullable=False, default="info")
    created_at = db.Column(db.DateTime(timezone=True), nullable=False, default=utc_now)

    job = db.relationship("Job", back_populates="events")
