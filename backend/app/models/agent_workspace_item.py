"""Append-only, versioned Agent workspace entries and write receipts."""

from copy import deepcopy

from sqlalchemy import event
from sqlalchemy.orm import object_session

from app.extensions import db
from app.models.base import SerializerMixin
from app.utils.time_utils import utc_now


class AgentWorkspaceItem(db.Model, SerializerMixin):
    __tablename__ = "agent_workspace_items"

    id = db.Column(db.Integer, primary_key=True)
    run_id = db.Column(db.String(80), db.ForeignKey("agent_runs.run_id"), nullable=False, index=True)
    key = db.Column(db.String(120), nullable=False)
    version = db.Column(db.Integer, nullable=False)
    kind = db.Column(db.String(40), nullable=False)
    payload = db.Column(db.JSON, nullable=False)
    artifact_ids = db.Column(db.JSON, nullable=False, default=list)
    author_agent = db.Column(db.String(40), nullable=False)
    delegation_id = db.Column(db.Integer, db.ForeignKey("agent_delegations.id"), nullable=False)
    request_key = db.Column(db.String(128), nullable=False)
    inputs_hash = db.Column(db.String(64), nullable=False)
    created_at = db.Column(db.DateTime(timezone=True), nullable=False, default=utc_now)

    __table_args__ = (
        db.UniqueConstraint("run_id", "key", "version", name="uq_agent_workspace_version"),
        db.UniqueConstraint("run_id", "request_key", name="uq_agent_workspace_request"),
        db.CheckConstraint("version >= 1", name="ck_agent_workspace_version_positive"),
    )

    def to_dict(self):
        return deepcopy(super().to_dict())


@event.listens_for(AgentWorkspaceItem, "before_update")
def _reject_update(_mapper, _connection, target):
    session = object_session(target)
    if session and session.is_modified(target, include_collections=False):
        raise ValueError("Workspace entries are immutable; append a new version")


@event.listens_for(AgentWorkspaceItem, "before_delete")
def _reject_delete(_mapper, _connection, _target):
    raise ValueError("Workspace entries are append-only")
