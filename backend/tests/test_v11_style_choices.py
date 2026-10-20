"""Distinct per-image requirements stay explicit through real Mock choice execution."""
from copy import deepcopy
import json
from pathlib import Path

import pytest

import app as app_package
from app.agent import plan_versions as versions
from app.agents.skill_library import SkillLibrary
from app.agents.workspace import write_workspace
from app.extensions import db
from app.models import ApiTask, ToolInvocation
from app.plans import runtime
from app.plans.compiler import compile_plan
from app.plans.dry_run import dry_run
from app.plans.views import public_plan
from app.services.job_run_service import JobRunService
from app.tools import build_v3_registry
from app.tools.budget import BudgetGuard
from tests.test_v3_workspace import brief, make_context
from tests.test_v4_execution import drain_plan

pytestmark=pytest.mark.config(AGENT_MODE_ENABLED=True,AGENT_V3_ENABLED=True,T2V_ENABLED=True)
SKILLS_ROOT=Path(app_package.__file__).resolve().parents[1]/"skills"
STYLES=[("watercolor","水彩"),("cyberpunk","赛博朋克"),("cut_paper","剪纸")]


def resource(kind):
    return f"resources/examples/three-style-{kind}-choice.plan.json"


def example(kind):
    return json.loads((SKILLS_ROOT/"plan-review"/resource(kind)).read_text(encoding="utf-8"))


@pytest.mark.parametrize("kind",["image","video"])
def test_style_resources_are_discoverable_and_explicit_per_image(kind):
    library=SkillLibrary(SKILLS_ROOT,build_v3_registry(),strict=True)
    review=library.load_skill("plan-review")
    assert resource(kind) in review["resources"]
    draft=json.loads(library.read_skill_resource("plan-review",resource(kind))["content"])
    generators=draft["nodes"][:3]
    assert [item["id"] for item in generators]==[key for key,_ in STYLES]
    for item,(_key,style) in zip(generators,STYLES):
        assert item["tool"]=="generate_image" and item["params"]["n"]==1
        assert style in item["inputs"]["prompt"]
        assert all(other not in item["inputs"]["prompt"] for _,other in STYLES if other!=style)
        assert item.get("model_id") is None and item.get("gate") is None
    selector=draft["nodes"][3]
    assert selector["tool"]=="select_image" and selector["gate"]=="choice"
    assert selector["inputs"]=={"candidate_artifact_ids":[{"ref":key+".image"} for key,_ in STYLES]}
    image_body=library.load_skill("image-create")["body"]
    assert "N 个独立 generate_image" in image_body and resource(kind) in image_body
    assert "n=N" in image_body and "Mock" in image_body
    assert "演示数据" in draft["goal"]
    assert len({item["inputs"]["prompt"] for item in generators})==3
    if kind=="video":
        assert draft["nodes"][-1]["inputs"]["first_frame_artifact_id"]=={"ref":"choice.image"}


@pytest.mark.parametrize("kind",["image","video"])
def test_exact_style_example_compiles_and_third_user_choice_drives_delivery(app_ctx,monkeypatch,kind):
    draft=example(kind)
    original=deepcopy(draft)
    run,_root,ctx=make_context(text="水彩、赛博朋克、剪纸各做一张猫海报，让我选一个"+("再做5秒跳舞视频" if kind=="video" else "交付"))
    write_workspace("brief","brief",brief(deliverable=kind,summary=run.request["text"]),ctx)
    registry=build_v3_registry()
    checked=compile_plan(draft,run,registry=registry,plan_version=1)
    assert checked["issues"]==[],checked["issues"]
    assert draft==original
    checked["dry_run"]=dry_run(checked,registry=registry)
    assert checked["dry_run"]["passed"],checked["dry_run"]
    assert ApiTask.query.count()==ToolInvocation.query.count()==0
    version=versions.create_version(run,checked["plan"],{},checked,author="system")
    run.status="awaiting_plan_review"
    db.session.commit()
    assert runtime.advance(run,registry)=="awaiting_plan_review"
    assert ApiTask.query.count()==0
    monkeypatch.setattr(JobRunService,"start",JobRunService.run_inline)
    runtime.begin(run,version,registry=registry)
    assert drain_plan(run,registry)=="awaiting_gate"
    tasks=runtime.latest_tasks(run)
    ids=[tasks[key].output["image"] for key,_ in STYLES]
    assert len(set(ids))==3
    assert ApiTask.query.count()==3
    assert ToolInvocation.query.filter_by(tool_name="generate_image").count()==3
    assert not ToolInvocation.query.filter_by(tool_name="animate_shot").first()
    for key,style in STYLES:
        assert style in tasks[key].inputs["prompt"]
        assert tasks[key].inputs["params"]["n"]==1
    selector=tasks["choice"]
    assert selector.status=="pending" and selector.inputs=={} and selector.invocation_id is None
    shown=next(item["choice"] for item in public_plan(run)["nodes"] if item["node_id"]=="choice")
    assert shown["ready"] and shown["selected_artifact_id"] is None
    assert [row["artifact_id"] for row in shown["candidates"]]==ids
    before=BudgetGuard.spent(run.run_id)
    runtime.approve_gate(run,version.version,"choice",selected_artifact_id=ids[2],choice_digest=shown["choice_digest"])
    assert BudgetGuard.spent(run.run_id)==before
    assert drain_plan(run,registry)=="awaiting_result_review"
    tasks=runtime.latest_tasks(run)
    assert tasks["choice"].output=={"image":ids[2]}
    if kind=="video":
        assert tasks["clip"].inputs["first_frame_artifact_id"]==ids[2]
        assert tasks["clip"].inputs["first_frame_artifact_id"]!=ids[0]
        assert ToolInvocation.query.filter_by(tool_name="animate_shot").count()==1
        assert ApiTask.query.count()==4
    else:
        assert ApiTask.query.count()==3
    assert checked["estimates"]["total_credits"]==sum(task.estimated_cost for task in tasks.values())
    assert BudgetGuard.spent(run.run_id)==checked["estimates"]["total_credits"]
    assert runtime.approve_results(run,version.version)=="success"
