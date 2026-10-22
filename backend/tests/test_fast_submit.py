"""Inline submit_plan: one Producer call saves, compiles, dry-runs and submits a draft."""

import json

import pytest

from app.api import AppError
from app.models import AgentDelegation, AgentPlanVersion, AgentWorkspaceItem, Job
from tests.test_v3_plan_compiler import make_run, node, plan
from tests.test_v3_plan_tools import invoke, registry, save


def test_inline_plan_is_saved_as_a_normal_draft_and_submitted(app_ctx):
    run = make_run()
    value = registry()
    before_jobs = Job.query.count()
    result = invoke(value, "submit_plan", {"plan": plan()}, run, "inline")
    item = AgentWorkspaceItem.query.filter_by(run_id=run.run_id, kind="plan_draft").one()
    assert (item.key, item.version, item.author_agent) == ("draft", 1, "producer")
    assert result["submitted"] and result["plan_ref"] == {"key": "draft", "version": 1}
    assert run.status == "awaiting_plan_review"
    producer = AgentDelegation.query.filter_by(run_id=run.run_id, agent="producer").one()
    assert producer.output["plan_ref"] == {"key": "draft", "version": 1}
    assert Job.query.count() == before_jobs
    # A replay of the same call returns the same receipt without a second draft or version.
    assert invoke(value, "submit_plan", {"plan": plan()}, run, "inline") == result
    assert AgentWorkspaceItem.query.filter_by(kind="plan_draft").count() == 1
    assert AgentPlanVersion.query.count() == 1


def test_inline_plan_with_issues_is_saved_but_not_submitted(app_ctx):
    run = make_run()
    value = registry()
    rejected = invoke(value, "submit_plan", {"plan": plan([node(model_id="not_a_model")])}, run, "bad")
    assert not rejected["submitted"] and rejected["issues"]
    assert AgentPlanVersion.query.count() == 0 and run.status == "queued"
    fixed = invoke(value, "submit_plan", {"plan": plan()}, run, "fixed")
    assert fixed["submitted"] and fixed["plan_ref"] == {"key": "draft", "version": 2}


def test_inline_submit_keeps_role_and_exclusivity_rules(app_ctx):
    run = make_run()
    value = registry()
    with pytest.raises(AppError):
        invoke(value, "submit_plan", {"plan": plan()}, run, "director", "director")
    assert AgentWorkspaceItem.query.filter_by(kind="plan_draft").count() == 0
    ref = save(run, plan())
    with pytest.raises(AppError):
        invoke(value, "submit_plan", {"plan": plan(), "plan_ref": ref}, run, "both")


def test_submit_schema_does_not_repeat_the_plan_draft_schema(app_ctx):
    schema = registry().function_schemas(["submit_plan"])[0]["function"]["parameters"]
    assert schema["properties"]["plan"]["type"] == "object"
    assert len(json.dumps(schema)) < 1500


def test_unknown_parameter_issue_names_the_param_and_the_allowed_ones(app_ctx):
    run = make_run()
    bad = plan([node(params={"n": 1, "aspect_ratio": "16:9"})])
    result = invoke(registry(), "submit_plan", {"plan": bad}, run, "bad-param")
    issue = next(item for item in result["issues"] if item["code"] == "INVALID_INPUT")
    assert "params.aspect_ratio" in issue["details"]["fields"]
    assert "n" in issue["details"]["allowed_params"] and "aspect_ratio" not in issue["details"]["allowed_params"]


def test_wrong_deliverable_output_lists_the_tool_outputs(app_ctx):
    run = make_run()
    bad = plan()
    bad["deliverables"][0]["output"] = "video"
    result = invoke(registry(), "submit_plan", {"plan": bad}, run, "bad-output")
    issue = next(item for item in result["issues"] if item["code"] == "INVALID_DELIVERABLE")
    assert issue["details"]["output"] == "video" and "image" in issue["details"]["available_outputs"]
