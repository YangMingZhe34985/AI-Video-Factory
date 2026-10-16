"""Fixed offline baselines; measures orchestration, not model quality or provider latency."""
import time

import pytest

from app.models import ApiTask, JobNodeRun
from app.services.job_package_service import JobPackageService
from app.skills import build_default_registry
from app.skills.budget import estimate_nodes_cost
from app.skills.spec import ToolContext
from app.agent.planning import SPECS
from tests.test_agent_mvp import action, create, detail, finish, tick

pytestmark = pytest.mark.config(AGENT_MODE_ENABLED=True)


@pytest.mark.parametrize("subject", ["orange cat", "small dog"])
@pytest.mark.parametrize("mode", ["classic", "single_creative", "director_creative"])
def test_fixed_offline_baselines(app_ctx, client, h, source_video, record_property, subject, mode):
    started = time.monotonic()
    approvals = 0
    if mode == "classic":
        job = h.run_full(h.make_job(source_video=source_video, name=subject).job_id)
        assert job.status == "success"
        JobPackageService.create_or_refresh(job)
        cost = estimate_nodes_cost({row.node_key for row in JobNodeRun.query.filter_by(job_id=job.id, status="success")})
    elif mode == "single_creative":
        registry = build_default_registry()
        registry.register(next(spec for spec in SPECS if spec.name == "agent_creative"))
        goal = f"A {subject} slowly turns and waves, one 5-second shot"
        plan = registry.invoke("agent_creative", {
            "original_goal": goal, "shot_count": 1,
            "brief": {"title": subject, "objective": goal, "visual_style": "bright room", "story_arc": "turn and wave"},
        }, ToolContext(role="creative", budget_scope="offline-evaluation", budget_limit=14))
        result = registry.invoke("produce_shot", plan["output"]["shots"][0],
            ToolContext(role="production", approved=True, budget_scope="offline-evaluation", budget_limit=14))
        job = h.wait_for_terminal(result["output"]["job_id"])
        assert job.status == "success"
        JobPackageService.create_or_refresh(job)
        cost = plan["estimated_cost"] + result["estimated_cost"]
        approvals = 2
    else:
        run_id = create(client, goal=f"A {subject} slowly turns and waves, one 5-second shot", shot_count=1)
        tick()
        action(client, run_id, "approve")
        assert finish(client, run_id)["status"] == "awaiting_delivery"
        action(client, run_id, "deliver")
        tick()
        result = detail(client, run_id)
        assert result["status"] == "success"
        cost = result["estimated_spent"]
        approvals = 2
    assert ApiTask.query.count() == 2
    record_property("evaluation", {"case": subject, "mode": mode, "success": True,
        "elapsed_seconds": time.monotonic() - started, "estimated_credits": cost,
        "generation_tasks": 2, "approval_actions": approvals,
        "quality_score": None, "provider_mode": "mock"})
