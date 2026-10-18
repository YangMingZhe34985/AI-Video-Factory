"""Read-only business task monitoring; never accesses Redis or media."""
from flask import Blueprint, current_app, request
from flask_jwt_extended import get_jwt_identity

from app.api import api_success
from app.services.task_center_service import task_detail, task_list

bp = Blueprint("task_center", __name__, url_prefix="/api/task-center")


def owner():
    return get_jwt_identity() if current_app.config.get("API_AUTH_REQUIRED", True) else "local"


@bp.get("")
def list_tasks():
    return api_success(task_list(owner(), request.args))


@bp.get("/<source>/<task_id>")
def get_task(source, task_id):
    return api_success(task_detail(owner(), source, task_id, request.args))
