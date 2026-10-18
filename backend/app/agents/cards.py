"""Validated, repository-authored Agent cards; no model-selected permissions."""

from pathlib import Path
from typing import Literal

import yaml
from flask import current_app
from pydantic import BaseModel, ConfigDict, Field, model_validator

from app.tools.agent_chat import AGENT_ROLES


class AgentLimits(BaseModel):
    model_config = ConfigDict(extra="forbid")
    max_steps: int = Field(default=40, ge=1, le=1000, strict=True)
    max_llm_calls: int = Field(default=30, ge=1, le=1000, strict=True)
    planning_credits: float = Field(default=20, ge=0, allow_inf_nan=False)
    max_parallel_delegations: int = Field(default=4, ge=1, le=16, strict=True)


class AgentCard(BaseModel):
    model_config = ConfigDict(extra="forbid")
    name: str = Field(pattern=r"^[a-z][a-z_]{0,39}$")
    description: str = Field(min_length=1, max_length=300)
    accepts: dict[str, str]
    returns: str
    model_role: str
    tools: list[str]
    can_delegate_to: list[str] = Field(default_factory=list)
    limits: AgentLimits = Field(default_factory=AgentLimits)
    prompt: str

    @model_validator(mode="after")
    def check_identity(self):
        if self.name not in AGENT_ROLES or self.model_role != self.name:
            raise ValueError("Card name and model role must identify the same v3 Agent")
        if len(set(self.tools)) != len(self.tools) or "finish" not in self.tools:
            raise ValueError("Cards require unique tools including finish")
        if self.name in self.can_delegate_to or len(set(self.can_delegate_to)) != len(self.can_delegate_to):
            raise ValueError("Self or duplicate delegation is forbidden")
        return self


class AgentCatalog:
    def __init__(self, root: Path, registry):
        self.root = root.resolve()
        self.cards = {}
        self.prompts = {}
        for path in sorted((self.root / "cards").glob("*.yaml")):
            card = AgentCard.model_validate(yaml.safe_load(path.read_text(encoding="utf-8")))
            if path.stem != card.name or card.name in self.cards:
                raise ValueError("Card filename must match its unique name")
            registry.function_schemas(card.tools)
            prompt = (self.root / card.prompt).resolve()
            if not prompt.is_relative_to(self.root / "prompts") or not prompt.is_file():
                raise ValueError("Card prompt must be a repository prompt file")
            body = prompt.read_text(encoding="utf-8")
            if not body.strip() or len(body) > 12000:
                raise ValueError("Agent prompt is empty or too long")
            self.cards[card.name] = card
            self.prompts[card.name] = body
        if set(self.cards) != AGENT_ROLES:
            raise ValueError("All seven v3 Agent cards are required")
        for card in self.cards.values():
            if set(card.can_delegate_to) - self.cards.keys():
                raise ValueError("Delegation target does not exist")

    def describe(self):
        return [{"name": card.name, "description": card.description,
                 "accepts": card.accepts, "returns": card.returns}
                for card in self.cards.values()]


def init_agent_cards(app, registry):
    catalog = AgentCatalog(Path(__file__).parent, registry)
    app.extensions["agent_v3_cards"] = catalog
    return catalog


def get_catalog(registry=None):
    catalog = current_app.extensions.get("agent_v3_cards")
    if catalog is None:
        if registry is None:
            from app.tools import build_v3_registry
            registry = build_v3_registry()
        catalog = init_agent_cards(current_app, registry)
    return catalog
