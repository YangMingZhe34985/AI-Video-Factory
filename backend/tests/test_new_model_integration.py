"""Model upgrades exercise the existing Skill/Job/MQ paths with Mock only."""
import pytest

from app.extensions import db
from app.models import ApiTask, Artifact, ToolInvocation
from app.services.job_run_service import JobRunService
from app.services.model_service import ModelService
from app.skills import get_registry
from app.skills.budget import estimate_model_cost
from app.skills.spec import ToolContext
from tests.test_simple_generation_skills import portrait


def invoke(name, data, key):
    return get_registry().invoke(name, data, ToolContext(role="production", approved=True,
                                 budget_scope=key, idempotency_key=key, budget_limit=100))


def complete(h, job_id, mq):
    if mq:
        from tests.test_shared_queue import drain
        job = drain(job_id)
    else:
        job = h.wait_for_terminal(job_id)
    assert job.status == "success", job.error_summary
    return job


@pytest.mark.parametrize("model_id", ["qwen-image-3.0", "qwen-image-3.0-pro"])
@pytest.mark.parametrize("mode,mq", [("t2i", False), ("i2i", True)])
def test_qwen3_skill_multi_output_and_idempotency(app_ctx, h, model_id, mode, mq):
    app_ctx.config.update(MQ_ENABLED=mq, MQ_WORKER_ACTIVE=mq)
    data = {"prompt": "A cat wearing a tailored suit", "mode": mode, "model_id": model_id, "n": 3}
    if mode == "i2i":
        data["reference_artifact_ids"] = [portrait()]
    result = invoke("generate_image", data, "qwen3-integration")
    job = complete(h, result["output"]["job_id"], mq)
    assert Artifact.query.filter_by(job_id=job.id, artifact_type="first_frame_image").count() == 3
    task = ApiTask.query.filter_by(job_id=job.id).one()
    assert task.model_id == model_id and task.adapter_name == "dashscope_qwen_image"
    payload = (task.queue_data or {}).get("wire_payload") or task.request_payload
    assert payload["model"] == model_id and payload["parameters"]["n"] == 3
    content = payload["input"]["messages"][0]["content"]
    assert sum("image" in item for item in content) == (1 if mode == "i2i" else 0)
    entry = ToolInvocation.query.filter_by(invocation_id=result["invocation_id"]).one()
    assert entry.estimated_cost == estimate_model_cost(ModelService.get_model(model_id), {"n": 3})
    replay = invoke("generate_image", data, "qwen3-integration")
    assert replay["replayed"] and replay["output"]["job_id"] == job.job_id
    assert ApiTask.query.filter_by(job_id=job.id).count() == 1


@pytest.mark.parametrize("model_id", ["wan3.0-video", "wan3.0-video-prime"])
@pytest.mark.parametrize("bridge,mq", [(False, False), (True, True)])
def test_unified_wan3_animate_and_bridge_cost(app_ctx, h, model_id, bridge, mq):
    app_ctx.config.update(MQ_ENABLED=mq, MQ_WORKER_ACTIVE=mq, AGENT_ENABLE_KEYFRAME_BRIDGE=bridge)
    data = {"prompt": "The cat waves", "model_id": model_id, "first_frame_artifact_id": portrait(),
            "params": {"duration": 4, "resolution": "480P"}}
    if bridge:
        data["last_frame_artifact_id"] = portrait()
    result = invoke("animate_shot", data, "wan3-integration")
    job = complete(h, result["output"]["job_id"], mq)
    assert Artifact.query.filter_by(job_id=job.id, artifact_type="i2v_video").count() == 1
    task = ApiTask.query.filter_by(job_id=job.id).one()
    assert task.model_id == model_id and task.adapter_name == "dashscope_wan3"
    payload = (task.queue_data or {}).get("wire_payload") or task.request_payload
    assert [item["type"] for item in payload["input"]["media"]] == (["first_frame", "last_frame"] if bridge else ["first_frame"])
    entry = ToolInvocation.query.filter_by(invocation_id=result["invocation_id"]).one()
    assert entry.estimated_cost == estimate_model_cost(ModelService.get_model(model_id), data["params"])
    assert invoke("animate_shot", data, "wan3-integration")["replayed"]
    assert ApiTask.query.filter_by(job_id=job.id).count() == 1


@pytest.mark.parametrize("mq", [False, True])
def test_classic_all_video_modes_accept_one_real_wan_id(app_ctx, h, source_video, mq):
    app_ctx.config.update(MQ_ENABLED=mq, MQ_WORKER_ACTIVE=mq)
    params = {"duration": 4, "resolution": "480P"}
    job = h.make_job(source_video, paths=("core", "first_i2v", "t2v", "r2v_flash"), job_config={
        "node_models": {key: "wan3.0-video" for key in ("submit_t2v", "submit_i2v", "submit_r2v_flash")},
        "node_model_params": {key: params for key in ("submit_t2v", "submit_i2v", "submit_r2v_flash")},
    })
    JobRunService.start(job.job_id, "run_full")
    complete(h, job.job_id, mq)
    db.session.expire_all()
    tasks = ApiTask.query.filter_by(job_id=job.id, model_id="wan3.0-video").all()
    assert {task.branch_key for task in tasks} >= {"t2v", "i2v", "r2v_flash"}
    assert all(task.adapter_name == "dashscope_wan3" for task in tasks)
    assert {"i2v_video", "t2v_video", "r2v_flash_video"} <= set(h.artifact_types(job))
