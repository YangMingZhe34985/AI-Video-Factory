"""V8d: production-workflow Skill examples submit in one inline submit_plan call."""
import json
import re

import pytest

from app.agents.cards import get_catalog
from app.agents.skill_library import get_skill_library
from app.agents.workspace import write_workspace
from app.models import AgentPlanVersion, Job
from app.tools import build_v3_registry
from tests.test_v3_workspace import make_context, next_context
from tests.test_v8_workflow_template import classic_template, source_video  # noqa: F401 - fixture

EXAMPLES = re.compile(r"<!-- workflow-example:([a-z]+) -->\s*```json\s*(.*?)\s*```", re.S)


def examples():
    body = get_skill_library().load_skill("production-workflow")["body"]
    found = {name: json.loads(raw) for name, raw in EXAMPLES.findall(body)}
    assert set(found) == {"reverse", "test", "production"}
    return found


@pytest.mark.parametrize("name", ["reverse", "test", "production"])
def test_each_workflow_example_submits_in_one_inline_call(app_ctx, source_video, name):
    template = classic_template()
    ids = [source_video] if name != "test" else []
    raw = json.dumps(examples()[name]).replace("REPLACE_TEMPLATE_ID", template.template_id)
    plan = json.loads(raw.replace("REPLACE_ATTACHMENT_ID", source_video))
    run, _root, ctx = make_context(ids=ids, text="把参考视频用于生产并保存到模板")
    brief = {"deliverable": "video", "summary": "经典路径示例", "confidence": 0.9, "production_intent": True,
             "attachments": [{"attachment_id": key, "kind": "video", "role": "content_ref",
                              "description": "参考视频", "reason": "反推提示词"} for key in ids]}
    write_workspace("brief", "brief", brief, ctx)
    before = Job.query.count()
    result = build_v3_registry().invoke("submit_plan", {"plan": plan}, next_context(ctx))["output"]
    assert result["submitted"], result["issues"]
    version = AgentPlanVersion.query.filter_by(run_id=run.run_id).one()
    assert version.check["template_writes"][0]["node_id"] == "workflow"
    assert Job.query.count() == before  # Submission never launches or writes templates.


def test_producer_routes_production_intent_to_the_skill(app_ctx):
    prompt = get_catalog().prompts["producer"]
    assert "production-workflow" in prompt and "绝不默认走经典路径" in prompt
    assert len(prompt) <= 14000
