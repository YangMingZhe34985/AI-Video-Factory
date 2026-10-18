"""Read-only knowledge tools; every Agent request enters through the Registry."""

from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, RootModel

from app.agents.skill_library import get_skill_library, NAME_PATTERN
from app.tools.permissions import READ
from app.tools.spec import ToolSpec
from app.tools.specs.list_models import V3_ROLES


class SkillToolModel(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)


class ListSkillsInput(SkillToolModel):
    agent: Literal["producer", "research", "creative", "director", "prompt_smith", "critic", "repair"] | None = None
    query: str | None = Field(default=None, min_length=1, max_length=200)


class SkillSummary(SkillToolModel):
    name: str
    description: str
    when_to_use: str
    blueprint: bool


class ListSkillsOutput(RootModel[list[SkillSummary]]):
    pass


class LoadSkillInput(SkillToolModel):
    name: str = Field(min_length=1, max_length=80, pattern=NAME_PATTERN)


class LoadSkillOutput(SkillToolModel):
    name: str
    version: int
    body: str
    resources: list[str]


class ReadSkillResourceInput(LoadSkillInput):
    path: str = Field(min_length=1, max_length=512)


class ReadSkillResourceOutput(SkillToolModel):
    name: str
    path: str
    content: str


def _list(data, _ctx):
    return get_skill_library().list_skills(data.agent, data.query)


def _load(data, _ctx):
    return get_skill_library().load_skill(data.name)


def _read(data, _ctx):
    return get_skill_library().read_skill_resource(data.name, data.path)


SPECS = (
    ToolSpec(name="list_skills", description="Find repository knowledge by Agent or topic; skills never execute tools.",
             input_model=ListSkillsInput, output_model=ListSkillsOutput, handler=_list,
             permission=READ, allowed_roles=V3_ROLES, agent_visible=True),
    ToolSpec(name="load_skill", description="Read a validated Skill before applying its knowledge; this grants no extra permissions.",
             input_model=LoadSkillInput, output_model=LoadSkillOutput, handler=_load,
             permission=READ, allowed_roles=V3_ROLES, agent_visible=True),
    ToolSpec(name="read_skill_resource", description="Read a named UTF-8 text resource from an already loaded repository Skill.",
             input_model=ReadSkillResourceInput, output_model=ReadSkillResourceOutput, handler=_read,
             permission=READ, allowed_roles=V3_ROLES, agent_visible=True),
)


def register_skill_tools(registry):
    for spec in SPECS:
        registry.register(spec)
    return registry
