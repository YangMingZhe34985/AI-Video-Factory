"""ToolRegistry enforcement: schema, roles, approval, budget, idempotency, retries."""

import pytest

from app.adapters.dashscope_i2v import DashScopeI2VAdapter
from app.api import AppError
from app.models import ApiTask, Artifact, Job, ToolInvocation
from app.services.job_service import JobService
from app.skills import get_registry
from app.skills.budget import BudgetGuard
from app.skills.spec import ToolContext

SHOT = {"shot_id": "s1", "first_frame_prompt": "a cat sits by the window", "i2v_prompt": "the cat jumps down"}
SHOT_COST = 12.0  # image (2) + video (10)


def invoke(name, data, role="production", approved=True, **ctx):
    return get_registry().invoke(name, data, ToolContext(role=role, approved=approved, **ctx))


def status(job_id=None, invocation_id=None):
    data = {"job_id": job_id} if job_id else {"invocation_id": invocation_id}
    return invoke("get_task_status", data)["output"]


def test_registry_exposes_all_tools_with_schemas(app_ctx):
    registry = get_registry()
    assert registry.names() == [
        "analyze_image",
        "analyze_video",
        "animate_shot",
        "compose_video",
        "download_reference",
        "extract_frame",
        "fetch_page",
        "generate_image",
        "generate_video",
        "get_task_status",
        "image_search",
        "package_project",
        "package_story",
        "probe_media",
        "produce_shot",
        "qc_video",
        "remix_shot",
        "rerun_node",
        "rewrite_prompt",
        "web_search",
    ]
    for spec in registry.describe_all():
        assert spec["input_schema"]["type"] == "object"
        assert spec["output_schema"]["type"] == "object"


@pytest.mark.parametrize(
    ("name", "data"),
    [
        ("produce_shot", {**SHOT, "unexpected": True}),
        ("produce_shot", {"shot_id": "s1", "first_frame_prompt": "x"}),
        ("generate_video", {"mode": "i2v", "prompt": "x"}),
        ("generate_video", {"mode": "t2v", "prompt": "x", "reference_artifact_ids": ["art_1"]}),
        ("get_task_status", {}),
    ],
)
def test_invalid_input_is_rejected_before_the_ledger(app_ctx, name, data):
    with pytest.raises(AppError) as exc:
        invoke(name, data)

    assert (exc.value.code, exc.value.status_code) == ("INVALID_INPUT", 422)
    assert ToolInvocation.query.count() == 0


def test_role_must_be_allowed(app_ctx):
    with pytest.raises(AppError) as exc:
        invoke("produce_shot", SHOT, role="creative")

    assert (exc.value.code, exc.value.status_code) == ("TOOL_FORBIDDEN", 403)
    assert ToolInvocation.query.count() == 0


def test_billed_tools_require_approval(app_ctx):
    with pytest.raises(AppError) as exc:
        invoke("produce_shot", SHOT, approved=False)

    assert exc.value.code == "APPROVAL_REQUIRED"
    assert ToolInvocation.query.count() == 0


@pytest.mark.parametrize(
    "params",
    [{"size": "999*999"}, {"not_a_param": 1}],
)
def test_invalid_model_params_are_rejected_without_spending(app_ctx, params):
    with pytest.raises(AppError) as exc:
        invoke("generate_image", {"prompt": "a cat", "params": params}, budget_scope="params")

    assert exc.value.code == "INVALID_INPUT"
    invocation = ToolInvocation.query.one()
    assert invocation.status == "rejected"
    assert invocation.job_id is None
    assert BudgetGuard.spent("params") == 0
    assert Job.query.count() == 0


def test_invalid_billable_quantity_is_rejected_before_ledger(app_ctx):
    with pytest.raises(AppError) as exc:
        invoke("generate_image", {"prompt": "a cat", "params": {"n": "two"}}, budget_scope="params")
    assert exc.value.code == "INVALID_INPUT"
    assert ToolInvocation.query.count() == Job.query.count() == ApiTask.query.count() == 0
    assert BudgetGuard.spent("params") == 0


def test_model_with_wrong_task_type_is_rejected(app_ctx):
    with pytest.raises(AppError) as exc:
        invoke("generate_image", {"prompt": "a cat", "model_id": "wan2.7-i2v"})

    assert exc.value.code == "INVALID_INPUT"
    assert "task_type" in exc.value.message


def test_budget_rejection_is_recorded_and_can_be_retried_with_more_budget(app_ctx, h):
    with pytest.raises(AppError) as exc:
        invoke("produce_shot", SHOT, budget_scope="tight", budget_limit=5)

    assert (exc.value.code, exc.value.status_code) == ("BUDGET_EXCEEDED", 402)
    rejected = ToolInvocation.query.one()
    assert rejected.status == "rejected"
    assert Job.query.count() == 0

    result = invoke("produce_shot", SHOT, budget_scope="tight", budget_limit=50)

    assert result["invocation_id"] == rejected.invocation_id
    assert result["replayed"] is False
    h.wait_for_terminal(result["output"]["job_id"])


def test_budget_accumulates_per_scope(app_ctx, h):
    for index in range(2):
        result = invoke("produce_shot", {**SHOT, "shot_id": f"s{index}"}, budget_scope="film", budget_limit=25)
        h.wait_for_terminal(result["output"]["job_id"])
    assert BudgetGuard.spent("film") == 2 * SHOT_COST

    with pytest.raises(AppError) as exc:
        invoke("produce_shot", {**SHOT, "shot_id": "s2"}, budget_scope="film", budget_limit=25)
    assert exc.value.code == "BUDGET_EXCEEDED"

    other = invoke("produce_shot", {**SHOT, "shot_id": "s2"}, budget_scope="other", budget_limit=25)
    h.wait_for_terminal(other["output"]["job_id"])


def test_identical_call_is_replayed_without_new_job_or_provider_task(app_ctx, h):
    first = invoke("produce_shot", SHOT)
    h.wait_for_terminal(first["output"]["job_id"])
    jobs, tasks = Job.query.count(), ApiTask.query.count()

    second = invoke("produce_shot", SHOT)

    assert second["replayed"] is True
    assert second["invocation_id"] == first["invocation_id"]
    assert second["output"]["job_id"] == first["output"]["job_id"]
    assert second["status"] == "success"
    assert (Job.query.count(), ApiTask.query.count()) == (jobs, tasks)
    assert BudgetGuard.spent("default") == SHOT_COST


def test_idempotency_key_cannot_be_reused_by_another_tool(app_ctx, h):
    result = invoke("produce_shot", SHOT, idempotency_key="shot-1")
    h.wait_for_terminal(result["output"]["job_id"])

    with pytest.raises(AppError) as exc:
        invoke("generate_image", {"prompt": "a cat"}, idempotency_key="shot-1")

    assert (exc.value.code, exc.value.status_code) == ("IDEMPOTENCY_KEY_CONFLICT", 409)


def test_failed_invocation_retries_on_the_same_job_without_resubmitting(app_ctx, h, monkeypatch):
    # A flag instead of monkeypatch.undo(), which would also lift the network block.
    provider_down = {"value": True}
    original_submit = DashScopeI2VAdapter.submit

    def flaky_submit(self, payload):
        if provider_down["value"]:
            raise AppError("API_TASK_FAILED", "injected i2v failure", 502)
        return original_submit(self, payload)

    monkeypatch.setattr(DashScopeI2VAdapter, "submit", flaky_submit)
    first = invoke("produce_shot", SHOT)
    job_id = first["output"]["job_id"]
    h.wait_for_terminal(job_id)
    report = status(job_id=job_id)
    assert report["status"] == "failed"
    assert report["invocation"]["status"] == "failed"
    assert "injected i2v failure" in report["error"]["summary"]

    provider_down["value"] = False
    retry = invoke("produce_shot", SHOT)

    assert retry["replayed"] is False
    assert retry["attempt"] == 2
    assert retry["output"]["job_id"] == job_id
    job = h.wait_for_terminal(job_id)
    assert job.status == "success"
    assert ApiTask.query.filter_by(job_id=job.id, branch_key="first_frame_image").count() == 1
    assert status(job_id=job_id)["invocation"]["status"] == "success"
    assert BudgetGuard.spent("default") == 2 * SHOT_COST


def test_retry_limit_is_enforced(app_ctx, h, monkeypatch):
    def failing_submit(self, payload):
        raise AppError("API_TASK_FAILED", "injected i2v failure", 502)

    monkeypatch.setattr(DashScopeI2VAdapter, "submit", failing_submit)
    for attempt in (1, 2):
        result = invoke("produce_shot", SHOT)
        assert result["attempt"] == attempt
        h.wait_for_terminal(result["output"]["job_id"])
        assert status(invocation_id=result["invocation_id"])["invocation"]["status"] == "failed"

    with pytest.raises(AppError) as exc:
        invoke("produce_shot", SHOT)

    assert (exc.value.code, exc.value.status_code) == ("RETRY_LIMIT_EXCEEDED", 409)


def test_rerun_node_only_touches_skill_jobs_for_agents(app_ctx, h, source_video):
    classic = h.run_full(h.make_job(source_video=source_video).job_id)
    request = {"job_id": classic.job_id, "node_key": "poll_i2v"}

    with pytest.raises(AppError) as exc:
        invoke("rerun_node", request)
    assert exc.value.code == "TOOL_FORBIDDEN"

    result = invoke("rerun_node", request, role="system")
    assert result["output"]["status"] == "running"
    assert h.wait_for_terminal(classic.job_id).status == "partial_success"


def test_package_project_is_not_deduplicated(app_ctx, h):
    shot = invoke("produce_shot", SHOT)
    h.wait_for_terminal(shot["output"]["job_id"])

    first = invoke("package_project", {"job_ids": [shot["output"]["job_id"]]})
    second = invoke("package_project", {"job_ids": [shot["output"]["job_id"]]})

    assert first["invocation_id"] != second["invocation_id"]
    assert second["replayed"] is False
    assert first["output"]["packages"][0]["artifact_id"] == second["output"]["packages"][0]["artifact_id"]


def test_ledger_survives_job_deletion(app_ctx, h):
    result = invoke("produce_shot", SHOT)
    job = h.wait_for_terminal(result["output"]["job_id"])

    JobService.delete_job(job.job_id, job.job_id)

    invocation = ToolInvocation.query.filter_by(invocation_id=result["invocation_id"]).one()
    assert invocation.estimated_cost == SHOT_COST
    assert Artifact.query.filter_by(job_id=job.id).count() == 0
    with pytest.raises(AppError) as exc:
        status(invocation_id=result["invocation_id"])
    assert exc.value.code == "JOB_NOT_FOUND"
