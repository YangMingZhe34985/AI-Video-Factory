"""Optional LangGraph Director / Creative / Production orchestration."""

from flask import current_app


def is_agent_mode_enabled(app=None) -> bool:
    config = (app or current_app).config
    return bool(config.get("AGENT_MODE_ENABLED", False))
