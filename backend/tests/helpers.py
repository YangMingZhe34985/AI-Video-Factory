"""Helpers shared by the regression tests (require an active app context)."""

from app.config import Config
from app.extensions import db
from app.models import Job, JobNodeRun
from app.services.artifact_service import ArtifactService
from app.services.job_run_state_service import JobRunStateService
from app.services.job_service import JobService
from app.services.workflow_service import WorkflowService


# Mirrors WORKFLOW_PATHS in frontend-vue/src/stores/workflow.js so tests submit
# the same node selections as the job wizard.
NODE_PATHS = {
    "core": ["reverse_prompts", "rewrite_prompts"],
    "first_i2v": ["submit_first_frame_image", "poll_first_frame_image", "submit_i2v", "poll_i2v"],
    "i2i_test": [
        "rewrite_t2i_to_i2i",
        "prepare_i2i_test_batch",
        "submit_i2i_test_image",
        "poll_i2i_test_image",
        "submit_i2i_test_i2v",
        "poll_i2i_test_i2v",
    ],
    "t2v": ["submit_t2v", "poll_t2v"],
    "r2v_flash": ["reverse_prompts4r2v", "submit_r2v_flash", "poll_r2v_flash"],
}

ALL_NODE_KEYS = [node["node_key"] for node in Config.DEFAULT_WORKFLOW_NODES]

DELIVERABLE_VIDEO_TYPES = {"i2v_video", "t2v_video", "i2i_test_video", "r2v_flash_video", "r2v_flash_videos"}


def node_selection(*paths: str, extra: tuple[str, ...] = ()) -> dict:
    enabled = {"export_manifest", *extra}
    for path in paths:
        enabled.update(NODE_PATHS[path])
    return {
        "enabled_nodes": sorted(enabled),
        "disabled_nodes": sorted(set(ALL_NODE_KEYS) - enabled),
    }


def make_job(source_video=None, paths=("core", "first_i2v"), extra_nodes=(), **data) -> Job:
    payload = {"template_id": "default", **node_selection(*paths, extra=tuple(extra_nodes)), **data}
    if source_video is not None:
        payload["source_video_path"] = str(source_video)
    return JobService.create_job(payload)


def reload_job(job_id: str) -> Job:
    db.session.expire_all()
    return Job.query.filter_by(job_id=job_id).one()


def run_full(job_id: str, **kwargs) -> Job:
    WorkflowService.run_full(job_id, **kwargs)
    return reload_job(job_id)


def run_from(job_id: str, node_key: str, **kwargs) -> Job:
    WorkflowService.run_from(job_id, node_key, **kwargs)
    return reload_job(job_id)


def run_node(job_id: str, node_key: str, **kwargs) -> Job:
    WorkflowService.run_node(job_id, node_key, **kwargs)
    return reload_job(job_id)


def artifacts(job: Job, include_history: bool = False) -> list[dict]:
    return ArtifactService.list_for_job(job, include_history=include_history)


def artifact_types(job: Job, include_history: bool = False) -> list[str]:
    return [item["artifact_type"] for item in artifacts(job, include_history=include_history)]


def node_runs(job: Job, node_key: str | None = None, current_run_only: bool = True) -> list[JobNodeRun]:
    query = JobNodeRun.query.filter_by(job_id=job.id)
    if node_key:
        query = query.filter_by(node_key=node_key)
    runs = query.order_by(JobNodeRun.id.asc()).all()
    run_id = JobRunStateService.current_run_id(job) if current_run_only else None
    if run_id:
        runs = [run for run in runs if (run.input_snapshot or {}).get("run_id") == run_id]
    return runs


def latest_node_states(job: Job, current_run_only: bool = True) -> dict[str, str]:
    states = {}
    for run in node_runs(job, current_run_only=current_run_only):
        states[run.node_key] = run.status
    return states
