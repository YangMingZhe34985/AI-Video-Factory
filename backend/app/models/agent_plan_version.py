from copy import deepcopy

from sqlalchemy import event
from sqlalchemy.orm import object_session

from app.extensions import db
from app.models.base import SerializerMixin
from app.utils.time_utils import utc_now


class AgentPlanVersion(db.Model, SerializerMixin):
    """Immutable story, production plan and validation snapshot."""

    __tablename__ = "agent_plan_versions"

    id = db.Column(db.Integer, primary_key=True)
    run_id = db.Column(db.String(80), db.ForeignKey("agent_runs.run_id"), nullable=False, index=True)
    version = db.Column(db.Integer, nullable=False)
    author = db.Column(db.String(20), nullable=False)
    parent_version = db.Column(db.Integer)
    plan = db.Column(db.JSON, nullable=False)
    story_package = db.Column(db.JSON, nullable=False)
    check = db.Column(db.JSON, nullable=False)
    created_at = db.Column(db.DateTime(timezone=True), nullable=False, default=utc_now)

    __table_args__ = (
        db.UniqueConstraint("run_id", "version", name="uq_agent_plan_run_version"),
        db.CheckConstraint("version >= 1", name="ck_agent_plan_version_positive"),
    )

    def to_dict(self):
        return deepcopy(super().to_dict())


@event.listens_for(AgentPlanVersion, "before_update")
def _reject_version_update(_mapper, _connection, target):
    session = object_session(target)
    if session and session.is_modified(target, include_collections=False):
        raise ValueError("Agent plan versions are immutable; create a new version")
