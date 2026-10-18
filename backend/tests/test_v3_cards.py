"""Repository card validation and server-owned tool visibility."""

import json
from pathlib import Path
from shutil import copytree

import pytest

from app.agents.cards import AgentCatalog, get_catalog
from app.api import AppError
from app.tools import build_v3_registry


@pytest.fixture
def card_copy(app_ctx, tmp_path):
    source = Path(__file__).resolve().parents[1] / "app" / "agents"
    root = tmp_path / "agent_catalog"
    copytree(source / "cards", root / "cards")
    copytree(source / "prompts", root / "prompts")
    return root, build_v3_registry()


def change(root, role, **values):
    path = root / "cards" / f"{role}.yaml"
    value = json.loads(path.read_text(encoding="utf-8"))
    value.update(values)
    path.write_text(json.dumps(value), encoding="utf-8")


def test_catalog_has_seven_roles_and_private_prompt_limits(app_ctx):
    catalog = get_catalog()
    assert set(catalog.cards) == {"producer", "research", "creative", "director", "prompt_smith", "critic", "repair"}
    assert all(set(item) == {"name", "description", "accepts", "returns"} for item in catalog.describe())


@pytest.mark.parametrize("values", [
    {"tools": ["generate_image", "finish"]},
    {"tools": ["not_registered", "finish"]},
    {"tools": ["finish", "finish"]},
    {"tools": ["list_agents"]},
    {"can_delegate_to": ["producer"]},
    {"can_delegate_to": ["missing"]},
    {"can_delegate_to": ["research", "research"]},
    {"model_role": "research"},
    {"prompt": "../outside.md"},
    {"description": "x" * 301},
    {"limits": {"max_steps": 0}},
])
def test_invalid_cards_fail_startup(card_copy, values):
    root, registry = card_copy
    change(root, "producer", **values)
    with pytest.raises((ValueError, AppError)):
        AgentCatalog(root, registry)


def test_missing_role_is_not_silently_loaded(card_copy):
    root, registry = card_copy
    (root / "cards" / "critic.yaml").unlink()
    with pytest.raises(ValueError, match="seven"):
        AgentCatalog(root, registry)


def test_prompt_escape_is_rejected_even_if_file_exists(card_copy):
    root, registry = card_copy
    (root / "outside.md").write_text("Untrusted prompt", encoding="utf-8")
    change(root, "producer", prompt="outside.md")
    with pytest.raises(ValueError, match="prompt"):
        AgentCatalog(root, registry)


def test_agent_function_visibility_does_not_include_future_execution_tools(app_ctx):
    catalog = get_catalog()
    registry = build_v3_registry()
    forbidden = {"agent_llm_turn", "submit_plan", "instantiate_blueprint", "request_preview", "propose_patch"}
    for card in catalog.cards.values():
        assert not forbidden.intersection(card.tools)
        assert all(registry.get(name).agent_visible for name in card.tools)
