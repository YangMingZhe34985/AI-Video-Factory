from flask import Blueprint, current_app, jsonify
from sqlalchemy import func

from app.api import api_success
from app.extensions import db
from app.models import Artifact, Job, JobNodeRun, Template
from app.models.series import Series

bp = Blueprint("dashboard", __name__, url_prefix="/api/dashboard")


@bp.get("/summary")
def summary():
    total_jobs = db.session.query(func.count(Job.id)).scalar() or 0
    queued = Job.query.filter_by(status="queued").count()
    running = Job.query.filter_by(status="running").count()
    success_count = Job.query.filter_by(status="success").count()
    failed_count = Job.query.filter_by(status="failed").count()
    paused = Job.query.filter_by(status="paused").count()
    partial = Job.query.filter_by(status="partial_success").count()

    total_series = 0
    try:
        total_series = db.session.query(func.count(Series.id)).scalar() or 0
    except Exception:
        pass

    return api_success({
        "total_series": total_series,
        "total_templates": db.session.query(func.count(Template.id)).scalar() or 0,
        "total_jobs": total_jobs,
        "queued": queued,
        "running": running,
        "success": success_count,
        "failed": failed_count,
        "paused": paused,
        "partial_success": partial,
        "total_artifacts": db.session.query(func.count(Artifact.id)).scalar() or 0,
        "total_node_runs": db.session.query(func.count(JobNodeRun.id)).scalar() or 0,
    })


health_bp = Blueprint("health", __name__)


@health_bp.get("/api/health")
def health():
    return jsonify({
        "success": True,
        "data": {
            "status": "healthy",
            "mode": current_app.config.get("MODEL_ADAPTER_MODE", "auto"),
        },
    })
