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


def test_agent_function_visibility_excludes_execution_and_limits_patch_roles(app_ctx):
    catalog = get_catalog()
    registry = build_v3_registry()
    forbidden = {"agent_llm_turn", "generate_image", "generate_video", "animate_shot", "transform_video",
                 "retain_video_segment", "compose_video", "extract_frame", "probe_media", "qc_video", "package_story"}
    for card in catalog.cards.values():
        assert not forbidden.intersection(card.tools)
        assert all(registry.get(name).agent_visible for name in card.tools)
        if card.name != "producer":
            assert "submit_plan" not in card.tools
        assert ("propose_patch" in card.tools) == (card.name in {"director", "repair"})
        assert ("review_patch" in card.tools) == (card.name == "director")
        assert all(registry.get(name).permission != "generate" or name == "request_preview" for name in card.tools)
    assert {"check_plan", "instantiate_blueprint", "submit_plan", "request_preview"}.issubset(catalog.cards["producer"].tools)
