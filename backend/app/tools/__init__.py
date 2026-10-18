"""Tool layer: validated, permissioned, budgeted, idempotent tools over the
existing business services. Agents must execute tools only via get_registry().
"""

_registry = None


def build_default_registry():
    from app.tools.registry import ToolRegistry
    from app.tools.specs import ALL_SPECS

    registry = ToolRegistry()
    for spec in ALL_SPECS:
        registry.register(spec)
    return registry


def get_registry():
    global _registry
    if _registry is None:
        _registry = build_default_registry()
    return _registry


def build_v3_registry():
    """Extend the legacy catalog without changing the public v1/v2 API."""
    from app.tools.specs import analyze_images, list_models, estimate_cost

    from dataclasses import replace
    from app.tools.registry import ToolRegistry
    from app.tools.specs import ALL_SPECS
    roles = frozenset({"producer", "research", "creative", "director", "prompt_smith", "critic", "repair"})
    registry = ToolRegistry()
    for spec in ALL_SPECS:
        registry.register(replace(spec, allowed_roles=spec.allowed_roles | roles) if spec.agent_visible else spec)
    for module in (analyze_images, list_models, estimate_cost):
        registry.register(module.SPEC)
    from app.tools.specs.skill_library import register_skill_tools
    from app.agents.tools import register_agent_tools
    register_skill_tools(registry)
    register_agent_tools(registry)
    return registry
