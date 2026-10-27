"""Plan node: run the classic workflow under a user's series/template (V.25.2).

Only an approved Plan can execute it (D-029); the Job is a normal classic Job,
so the classic JobDetail page, prompt management and packaging apply as-is.
"""

from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator

from app.api import AppError
from app.extensions import db
from app.models import Template
from app.tools import job_backed
from app.tools.permissions import GENERATE, PRODUCTION, SYSTEM
from app.tools.spec import ToolContext, ToolSpec

Branch = Literal["reverse_prompts", "rewrite_prompts", "r2v_prompt", "t2v", "first_frame_image", "i2v", "r2v", "i2i_test"]
Prompt = Field(default=None, min_length=1, max_length=8000)


class Strict(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True, allow_inf_nan=False)


class Prompts(Strict):
    t2v: str | None = Prompt
    first_frame_image: str | None = Prompt
    i2v: str | None = Prompt
    r2v_flash: str | None = Prompt
    i2i: str | None = Prompt


class I2ITest(Strict):
    mode: Literal["single_male", "single_female", "couple"]
    test_count: int = Field(ge=1, le=8, strict=True)


class RunWorkflowInput(Strict):
    template_target: dict
    branches: list[Branch] = Field(min_length=1, max_length=8)
    source_video_artifact_id: str | None = Field(default=None, min_length=1, max_length=100)
    first_frame_artifact_id: str | None = Field(default=None, min_length=1, max_length=100)
    reference_artifact_ids: list[str] | None = Field(default=None, min_length=1, max_length=4)
    prompts: Prompts = Field(default_factory=Prompts)
    i2i_test: I2ITest | None = None
    models: dict[str, str] = Field(default_factory=dict, max_length=12)
    model_params: dict[str, dict] = Field(default_factory=dict, max_length=12)
    package: bool = True

    @model_validator(mode="after")
    def unique_branches(self):
        if len(set(self.branches)) != len(self.branches):
            raise ValueError("Workflow branches must be unique")
        return self


def _template(target, ctx, node_id):
    from app.plans.workflow import resolve_target
    resolved = resolve_target(target, ctx.budget_scope, node_id)
    if resolved["mode"] == "existing":
        return resolved["template_id"]
    existing = Template.query.filter_by(template_id=resolved["template_id"]).first()
    if existing is not None:
        marker = (existing.config or {}).get("agent_created") or {}
        if marker != {"run_id": ctx.budget_scope, "node_id": node_id}:
            raise AppError("TEMPLATE_TARGET_CONFLICT", "Derived template ID belongs to another plan node", 409)
        return existing.template_id
    from app.services.prompt_service import PromptService
    PromptService.create_template({
        "template_id": resolved["template_id"], "name": resolved["template_name"], "series": resolved["series_id"],
        "description": "由 CineCrew Agent 经典路径计划创建。",
        "config": {"agent_created": {"run_id": ctx.budget_scope, "node_id": node_id}},
    })
    return resolved["template_id"]


def run(data: RunWorkflowInput, ctx: ToolContext):
    if getattr(ctx, "plan_node_task_id", None) is None:
        raise AppError("APPROVAL_REQUIRED", "Classic workflow runs only as an approved Plan node", 403)
    from app.plans import workflow
    from app.plans.policy import task_context
    _run, task, _version, _node = task_context(ctx)
    inputs = data.model_dump(mode="json")
    template_id = _template(data.template_target, ctx, task.node_id)
    db.session.commit()
    config = {"node_models": {}, "node_model_params": {},
              "agent_workflow": {"branches": list(data.branches), "test_count": workflow.test_count(inputs)}}
    for node_key, (slot, _calls) in workflow.operations(inputs).items():
        config["node_models"][node_key] = data.models[slot]
        if data.model_params.get(slot):
            config["node_model_params"][node_key] = data.model_params[slot]
    if data.i2i_test:
        config["i2i_test"] = data.i2i_test.model_dump()
    artifacts = {}
    if data.source_video_artifact_id:
        artifacts["source_video"] = data.source_video_artifact_id
    if data.first_frame_artifact_id:
        artifacts["first_frame_image"] = data.first_frame_artifact_id
    if data.reference_artifact_ids:
        artifacts["reference_images"] = list(data.reference_artifact_ids)
    for artifact_id in [data.source_video_artifact_id, data.first_frame_artifact_id, *(data.reference_artifact_ids or [])]:
        if artifact_id:
            job_backed.resolve_artifact(artifact_id, ctx=ctx)
    prompts = {key: value for key, value in data.prompts.model_dump().items() if value}
    job = job_backed.launch(ctx, workflow.enabled_nodes(inputs), template_id=template_id,
                            initial_prompts=prompts, initial_artifacts=artifacts, job_config=config)
    return job_backed.launch_output(job, sorted(workflow.produced_outputs(inputs)))


def cost(data, ctx):
    if getattr(ctx, "plan_node_task_id", None) is not None:
        from app.plans.policy import submission_cost
        return submission_cost(ctx)
    from app.plans.workflow import quote
    return quote(data.model_dump(mode="json"))["total"]


SPEC = ToolSpec(
    name="run_workflow_template",
    description="Run classic workflow branches under a series/template, writing prompt versions back to the template.",
    input_model=RunWorkflowInput, output_model=job_backed.JobLaunchOutput, handler=run,
    permission=GENERATE, allowed_roles=frozenset({PRODUCTION, SYSTEM}), requires_approval=True,
    plan_executable=True, max_retries=0, max_wait_sec=3600, cost_fn=cost,
    io_types={"inputs": {"source_video_artifact_id": "video", "first_frame_artifact_id": "image",
                         "reference_artifact_ids": "image[]"},
              "outputs": {"job_id": "json", "template": "json", "prompts": "json",
                          "videos": "video[]", "images": "image[]", "package": "package"}},
)
