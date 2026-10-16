"""Admission control; never strands already admitted sessions."""

from flask import current_app
from flask_jwt_extended import get_jwt_identity

from app.api import AppError


def ensure_admission():
    if not current_app.config.get("AGENT_ACCEPT_NEW_RUNS", True):
        raise AppError("AGENT_DRAINING", "New Agent work is paused; existing sessions can finish", 503)
    allowed = {item.strip() for item in current_app.config.get("AGENT_ALLOWED_USERS", "").split(",") if item.strip()}
    identity = str(get_jwt_identity()) if current_app.config.get("API_AUTH_REQUIRED", True) else "local"
    if allowed and identity not in allowed:
        raise AppError("AGENT_NOT_IN_ROLLOUT", "Agent creation is not enabled for this user", 403)
