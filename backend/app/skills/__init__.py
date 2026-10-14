"""Skill layer: validated, permissioned, budgeted, idempotent tools over the
existing business services. Agents must execute tools only via get_registry().
"""

_registry = None


def build_default_registry():
    from app.skills.registry import ToolRegistry
    from app.skills.tools import ALL_SPECS

    registry = ToolRegistry()
    for spec in ALL_SPECS:
        registry.register(spec)
    return registry


def get_registry():
    global _registry
    if _registry is None:
        _registry = build_default_registry()
    return _registry
