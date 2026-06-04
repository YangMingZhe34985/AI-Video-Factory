from app.extensions import db
from app.models.base import SerializerMixin
from app.utils.time_utils import utc_now


class WorkflowNode(db.Model, SerializerMixin):
    __tablename__ = "workflow_nodes"
    __table_args__ = (
        db.UniqueConstraint("template_id", "node_key", name="uq_workflow_node_template_key"),
    )

    id = db.Column(db.Integer, primary_key=True)
    template_id = db.Column(db.Integer, db.ForeignKey("templates.id"), nullable=True)
    node_key = db.Column(db.String(120), nullable=False, index=True)
    display_name = db.Column(db.String(255), nullable=False)
    sequence = db.Column(db.Integer, nullable=False, index=True)
    branch_key = db.Column(db.String(80), nullable=False, default="core")
    enabled = db.Column(db.Boolean, nullable=False, default=True)
    depends_on = db.Column(db.JSON, nullable=False, default=list)
    config = db.Column(db.JSON, nullable=False, default=dict)
    created_at = db.Column(db.DateTime(timezone=True), nullable=False, default=utc_now)
    updated_at = db.Column(
        db.DateTime(timezone=True), nullable=False, default=utc_now, onupdate=utc_now
    )
