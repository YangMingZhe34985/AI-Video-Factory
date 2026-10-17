"""Retry estimates must match saved jobs and I2I's inline video submissions."""

import pytest

from app.api import AppError
from app.extensions import db
from app.models import ToolInvocation
from app.services.job_run_service import JobRunService
from app.services.model_service import ModelService
from app.services.workflow_service import WorkflowService
from app.skills import get_registry
from app.skills.budget import BudgetGuard
from app.skills.spec import ToolContext
from app.skills.tools.rerun_node import RerunNodeInput, estimate_cost


def _failed_video(h):
    WorkflowService.update_node_config("submit_t2v", {
        "model_id": "wan2.7-t2v", "model_params": {"duration": 15},
    })
    data = {"mode": "t2v", "prompt": "a dancing cat"}
    spec = get_registry().get("generate_video")
    job = h.make_job(paths=("t2v",), initial_prompts={"t2v": data["prompt"]},
                     job_config={"node_models": {"submit_t2v": "wan2.7-t2v"}})
    job.status = "failed"
    invocation = ToolInvocation(
        tool_name="generate_video", idempotency_key="retry-original", caller_role="production",
        budget_scope="retry-cost", status="failed", attempt=1, job=job, estimated_cost=15,
        input_payload=spec.input_model.model_validate(data).model_dump(mode="json"),
    )
    db.session.add(invocation)
    db.session.commit()
    WorkflowService.update_node_config("submit_t2v", {"model_params": {"duration": 5}})
    return data, job, invocation


def _retry_context(limit=100):
    return ToolContext(role="production", approved=True, idempotency_key="retry-original",
                       budget_scope="retry-cost", budget_limit=limit)


def test_failed_retry_uses_saved_duration_for_budget_and_execution(app_ctx, h, monkeypatch):
    data, job, invocation = _failed_video(h)
    starts = []

    def start(job_id, run_type, **_kwargs):
        starts.append((job_id, run_type, job.config["workflow_node_configs"]["submit_t2v"]["model_params"]["duration"]))
        job.status = "running"
        db.session.commit()
        return {"status": "running"}

    monkeypatch.setattr(JobRunService, "start", start)
    with pytest.raises(AppError) as rejected:
        get_registry().invoke("generate_video", data, _retry_context(limit=20))
    assert rejected.value.code == "BUDGET_EXCEEDED"
    assert rejected.value.payload["requested"] == 15
    assert starts == []
    assert invocation.attempt == 1
    assert BudgetGuard.spent("retry-cost") == 15

    result = get_registry().invoke("generate_video", data, _retry_context())
    assert result["output"]["job_id"] == job.job_id
    assert result["estimated_cost"] == 30
    assert starts == [(job.job_id, "run_full", 15)]
    assert BudgetGuard.spent("retry-cost") == 30


def test_failed_retry_rejects_changed_input_without_spending(app_ctx, h, monkeypatch):
    data, _job, invocation = _failed_video(h)
    starts = []
    monkeypatch.setattr(JobRunService, "start", lambda *args, **kwargs: starts.append(args))

    with pytest.raises(AppError) as rejected:
        get_registry().invoke("generate_video", {**data, "params": {"duration": 5}}, _retry_context())
    assert (rejected.value.code, rejected.value.status_code) == ("IDEMPOTENCY_KEY_CONFLICT", 409)
    assert invocation.attempt == 1
    assert invocation.status == "failed"
    assert starts == []
    assert BudgetGuard.spent("retry-cost") == 15


def _i2i_job(h):
    job = h.make_job(paths=())
    video = ModelService.get_model("wan2.7-i2v")
    video.capabilities = {**video.capabilities, "pricing": {"unit": "second", "credits_per_unit": 2}}
    job.config = {
        "i2i_test": {"test_count": 1},
        "i2i_test_batch": {"test_count": 2, "items": [{"test_index": i} for i in range(1, 5)]},
        "node_model_params": {"submit_i2i_test_i2v": {"duration": 5}},
        "workflow_node_configs": {
            "poll_i2i_test_image": {"model_id": "wan2.7-i2v", "model_params": {"duration": 15}},
            "submit_i2i_test_i2v": {"model_id": "wan2.6-i2v-flash"},
        },
    }
    job.node_overrides = h.node_selection(extra=("poll_i2i_test_image", "submit_i2i_test_i2v"))
    db.session.commit()
    return job


def test_rerun_uses_existing_batch_items_and_prices_inline_video(app_ctx, h):
    job = _i2i_job(h)
    # Polling uses its own selected model, but the submit node's parameter override.
    assert estimate_cost(RerunNodeInput(job_id=job.job_id, node_key="poll_i2i_test_image")) == 40
    assert estimate_cost(RerunNodeInput(job_id=job.job_id, node_key="submit_i2i_test_i2v")) == 20
    # Catch-up skips items submitted by polling. Reserve one batch at the higher rate.
    assert estimate_cost(RerunNodeInput(job_id=job.job_id, node_key="poll_i2i_test_image", mode="from")) == 40


def test_inline_video_rerun_cannot_bypass_budget_as_a_poll(app_ctx, h, monkeypatch):
    job = _i2i_job(h)
    starts = []
    monkeypatch.setattr(JobRunService, "start", lambda *args, **kwargs: starts.append(args))
    with pytest.raises(AppError) as rejected:
        get_registry().invoke(
            "rerun_node", {"job_id": job.job_id, "node_key": "poll_i2i_test_image"},
            ToolContext(role="system", approved=True, budget_scope="inline", budget_limit=39),
        )
    assert rejected.value.code == "BUDGET_EXCEEDED"
    assert rejected.value.payload["requested"] == 40
    assert starts == []
    assert BudgetGuard.spent("inline") == 0


def test_rerun_batch_creation_uses_saved_node_sample_count(app_ctx, h):
    job = h.make_job(paths=())
    job.config = {"workflow_node_configs": {
        "submit_i2i_test_image": {"i2i_test": {"test_count": 7}},
    }}
    db.session.commit()
    assert estimate_cost(RerunNodeInput(job_id=job.job_id, node_key="submit_i2i_test_image")) == 14
