"""Agent orchestration layer (skeleton).

Phase 1 only defines the feature flag and the plan protocol shared between
the Creative and Production roles. The LangGraph Director / Creative /
Production graph arrives in Phase 2 and will execute tools exclusively
through app.skills.get_registry().
"""

from flask import current_app


def is_agent_mode_enabled(app=None) -> bool:
    config = (app or current_app).config
    return bool(config.get("AGENT_MODE_ENABLED", False))
