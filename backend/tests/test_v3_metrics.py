"""v3 run metrics and owner-scoped rollout aggregate (D-064)."""
import pytest

from app.agents.workspace import write_workspace
from app.extensions import db
from app.models import AgentDelegation, AgentStep, ToolInvocation
from app.plans import runtime
from app.services.job_run_service import JobRunService
from tests.test_v3_workspace import brief, make_context
from tests.test_v4_execution import drain_plan, image_node, setup

pytestmark = pytest.mark.config(AGENT_MODE_ENABLED=True, AGENT_V3_ENABLED=True)


def planned_run(monkeypatch, *, tokens=(12000, 18000)):
    run, root, ctx = make_context(owner="local", text="生成一张猫的图片")
    write_workspace("brief", "brief", brief(), ctx)
    run, version, registry = setup([image_node()], run=run)
    for index, prompt_tokens in enumerate(tokens):
        db.session.add(ToolInvocation(tool_name="agent_llm_turn", idempotency_key=f"{run.run_id}:turn:{index}",
            caller_role="producer", caller_agent="producer", budget_scope=run.run_id, estimated_cost=0.1,
            status="success", output_payload={"usage": {"prompt_tokens": prompt_tokens, "completion_tokens": 300}}))
    db.session.add(AgentStep(run_id=run.run_id, delegation_id=root.id, step=0, kind="ask", agent="producer",
                             summary="提交澄清问题"))
    db.session.commit()
    monkeypatch.setattr(JobRunService, "start", JobRunService.run_inline)
    runtime.begin(run, version, registry=registry)
    assert drain_plan(run, registry) == "awaiting_result_review"
    return run


def test_run_metrics_report_planning_execution_and_alerts(app_ctx, client, monkeypatch):
    run = planned_run(monkeypatch, tokens=(12000, 85000))
    data = client.get(f"/api/agent/runs/{run.run_id}/metrics").json["data"]
    v3 = data["v3"]
    assert v3["planning"]["llm_rounds"] == 2 and v3["planning"]["input_tokens"] == 97000
    assert v3["planning"]["peak_input_tokens"] == 85000 and v3["planning"]["questions"] == 1
    assert v3["planning"]["reached_plan"] and v3["planning"]["seconds_to_first_plan"] is not None
    assert v3["execution"]["node_status"] == {"success": 1} and v3["execution"]["media_credits"] > 0
    assert "PEAK_INPUT_OVER_80K" in v3["alerts"]
    assert v3["cost_basis"] == "demonstration_credits_not_provider_bill"


def test_aggregate_is_owner_scoped_and_validates_window(app_ctx, client, monkeypatch):
    planned_run(monkeypatch)
    make_context(owner="someone-else", text="别人的任务")
    data = client.get("/api/agent/metrics/v3?days=7").json["data"]
    assert data["runs"] == 1 and data["reached_plan_rate"] == 1.0 and data["asked_rate"] == 1.0
    assert data["median_llm_rounds"] == 2 and data["peak_over_80k_runs"] == 0
    assert data["by_status"] == {"awaiting_result_review": 1}
    assert client.get("/api/agent/metrics/v3?days=0").status_code == 422
    assert client.get("/api/agent/metrics/v3?days=abc").status_code == 422
