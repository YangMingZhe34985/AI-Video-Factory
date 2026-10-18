"""Native Wan3 transformation; all costs and media facts remain server-derived."""
from pydantic import Field
from app.agent.request_spec import StrictModel
from app.plans.blueprints.common import TransformDraft, artifact, node, result


class Params(StrictModel):
    plan: TransformDraft
    goal: str | None = Field(default=None, min_length=1, max_length=2000)


def build(params, *, run, caller_agent="director"):
    data = Params.model_validate(params)
    plan = data.plan
    inputs = {"operation": plan.operation, "prompt": plan.prompt,
              "media": [{"type": item.type, "artifact_id": artifact(item.artifact_id)} for item in plan.media]}
    if plan.source_artifact_id:
        inputs["source_artifact_id"] = artifact(plan.source_artifact_id)
    nodes = [node("video", "transform_video", inputs, "video-transform", caller_agent,
                  model_id=plan.model_id, params=plan.params, stage="creation", rationale=plan.rationale)]
    return result(plan.title, data.goal, run, nodes, [{"kind": "video", "node_id": "video", "output": "video"}],
                  [{"id": "creation", "label": "视频变换"}],
                  ["输入时长由媒体检查确定，费用按输入视频秒数与完整输出秒数之和估算；演示单价不代表账单。"])
