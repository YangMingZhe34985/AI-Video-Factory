"""Producer fast-path examples submit in one inline submit_plan call (no reading rounds)."""
import json
import re

import pytest

from app.agents.cards import get_catalog
from app.agents.workspace import write_workspace
from app.models import AgentPlanVersion, Job
from app.tools import build_v3_registry
from tests.test_v3_workspace import image_attachment, make_context, next_context

pytestmark = pytest.mark.config(AGENT_MODE_ENABLED=True, AGENT_V3_ENABLED=True, T2V_ENABLED=True)
EXAMPLES = re.compile(r"<!-- fast-path-example:([a-z0-9-]+) -->\s*```json\s*(.*?)\s*```", re.S)
VIDEO = {"t2v", "first-frame-i2v", "style-choice"}


def examples():
    found = {name: json.loads(raw) for name, raw in EXAMPLES.findall(get_catalog().prompts["producer"])}
    assert set(found) == {"t2v", "first-frame-i2v", "edit", "style-choice"}
    return found


def brief(name, attachment_id=None):
    value = {"deliverable": "video" if name in VIDEO else "image", "summary": "快速通道示例", "confidence": 0.9}
    if name in VIDEO:
        value.update(aspect_ratio="16:9" if name != "style-choice" else "9:16", target_duration_sec=8 if name == "t2v" else 5,
                     duration_mode="approx", duration_source_text="约8秒" if name == "t2v" else "约5秒")
    if attachment_id:
        value.update(subjects=[{"name": "上传人物", "description": "保留身份", "source": "attachment",
                                "attachment_ids": [attachment_id]}],
                     attachments=[{"attachment_id": attachment_id, "kind": "image", "role": "identity_ref",
                                   "description": "上传头像", "reason": "保留身份做证件照"}])
    return value


@pytest.mark.parametrize("name", ["t2v", "first-frame-i2v", "edit", "style-choice"])
def test_each_fast_path_example_submits_in_one_inline_call(app_ctx, name):
    plan = examples()[name]
    attachment = image_attachment() if name == "edit" else None
    ids = [attachment.artifact_id] if attachment else []
    run, _root, ctx = make_context(ids=ids, text="快速通道示例：约8秒" if name == "t2v" else "快速通道示例：约5秒")
    if attachment:
        plan = json.loads(json.dumps(plan).replace("REPLACE_ATTACHMENT_ID", attachment.artifact_id))
    write_workspace("brief", "brief", brief(name, attachment.artifact_id if attachment else None), ctx)
    before = Job.query.count()
    result = build_v3_registry().invoke("submit_plan", {"plan": plan}, next_context(ctx))["output"]
    assert result["submitted"], result["issues"]
    assert run.status == "awaiting_plan_review" and AgentPlanVersion.query.count() == 1
    assert Job.query.count() == before


def test_minimal_multi_shot_compose_shape_from_the_fast_path_rule_submits(app_ctx):
    run, _root, ctx = make_context(text="两镜头短片：约10秒")
    value = {"deliverable": "video", "summary": "两镜头", "confidence": 0.9, "aspect_ratio": "16:9",
             "target_duration_sec": 10, "duration_mode": "approx", "duration_source_text": "约10秒"}
    write_workspace("brief", "brief", value, ctx)
    origin = {"agent": "producer", "skills": []}
    nodes = []
    for index in (1, 2):
        nodes.append({"id": f"frame{index}", "tool": "generate_image", "inputs": {"mode": "t2i", "prompt": f"镜头{index}首帧",
                      "reference_artifact_ids": []}, "model_id": None, "params": {"n": 1}, "origin": origin, "rationale": "首帧"})
        nodes.append({"id": f"shot{index}", "tool": "animate_shot", "inputs": {"first_frame_artifact_id": {"ref": f"frame{index}.image"},
                      "prompt": f"镜头{index}动作"}, "model_id": None, "params": {"duration": 5}, "origin": origin, "rationale": "镜头"})
    nodes.append({"id": "film", "tool": "compose_video", "inputs": {"video_artifact_ids": [{"ref": "shot1.video"}, {"ref": "shot2.video"}]},
                  "origin": origin, "rationale": "拼成一个成片"})
    plan = {"title": "两镜头", "goal": "约10秒", "nodes": nodes, "deliverables": [{"kind": "video", "node_id": "film", "output": "artifact_id"}]}
    result = build_v3_registry().invoke("submit_plan", {"plan": plan}, next_context(ctx))["output"]
    assert result["submitted"], result["issues"]
