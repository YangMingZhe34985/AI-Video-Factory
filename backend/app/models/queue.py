"""Database-owned dispatch and delivery records; Redis carries IDs only."""
from app.extensions import db
from app.utils.time_utils import utc_now
from sqlalchemy.dialects.mysql import DATETIME

QUEUE_TIME = db.DateTime(timezone=True).with_variant(DATETIME(fsp=6), "mysql")


class JobDispatch(db.Model):
    __tablename__ = "job_dispatches"
    id = db.Column(db.Integer, primary_key=True)
    job_id = db.Column(db.Integer, db.ForeignKey("jobs.id", ondelete="CASCADE"), unique=True, nullable=False)
    version = db.Column(db.String(80), nullable=False)
    command = db.Column(db.JSON, nullable=False)
    status = db.Column(db.String(24), nullable=False, default="ready", index=True)
    available_at = db.Column(QUEUE_TIME, nullable=False, default=utc_now)
    lease_token = db.Column(db.String(80))
    lease_until = db.Column(QUEUE_TIME)
    error = db.Column(db.Text)
    updated_at = db.Column(db.DateTime(timezone=True), nullable=False, default=utc_now, onupdate=utc_now)


class TaskOutbox(db.Model):
    __tablename__ = "task_outbox"
    id = db.Column(db.Integer, primary_key=True)
    event_key = db.Column(db.String(160), unique=True, nullable=False)
    task_id = db.Column(db.Integer, db.ForeignKey("api_tasks.id", ondelete="CASCADE"), nullable=False, index=True)
    phase = db.Column(db.String(24), nullable=False)
    generation = db.Column(db.Integer, nullable=False)
    available_at = db.Column(QUEUE_TIME, nullable=False, default=utc_now)
    published_at = db.Column(QUEUE_TIME)
    consumed_at = db.Column(QUEUE_TIME)
    attempts = db.Column(db.Integer, nullable=False, default=0)
    lease_token = db.Column(db.String(80))
    lease_until = db.Column(QUEUE_TIME)
    last_error = db.Column(db.Text)
    created_at = db.Column(db.DateTime(timezone=True), nullable=False, default=utc_now)
    __table_args__ = (db.Index("ix_outbox_due", "consumed_at", "available_at"),)
