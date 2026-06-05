from __future__ import annotations

from app.extensions import db
from app.models import Job, JobNodeRun
from app.utils.ids import new_id
from app.utils.time_utils import utc_now


class JobRunStateService:
    """Track the UI-visible run batch without adding database columns."""

    CONFIG_KEY = "current_run"

    @classmethod
    def begin_restart(cls, job: Job, enabled_nodes: list[str] | None = None) -> dict:
        config = dict(job.config or {})
        node_overrides = job.node_overrides or {}
        current_run = {
            "run_id": new_id("jr"),
            "mode": "restart_full",
            "started_at": utc_now().isoformat(),
            "enabled_nodes": list(enabled_nodes or []),
            "disabled_nodes": list(node_overrides.get("disabled_nodes") or []),
            "prompt_policy": "template_first",
            "artifact_visibility": "current_only",
        }
        config[cls.CONFIG_KEY] = current_run
        job.config = config
        job.current_node = None
        job.error_summary = None
        db.session.add(job)
        return current_run

    @classmethod
    def current(cls, job: Job | None) -> dict:
        if not job:
            return {}
        current_run = (job.config or {}).get(cls.CONFIG_KEY)
        return current_run if isinstance(current_run, dict) else {}

    @classmethod
    def current_run_id(cls, job: Job | None) -> str | None:
        return cls.current(job).get("run_id")

    @classmethod
    def is_restart_run(cls, job: Job | None) -> bool:
        return cls.current(job).get("mode") == "restart_full"

    @classmethod
    def prompt_policy(cls, job: Job | None) -> str | None:
        return cls.current(job).get("prompt_policy")

    @classmethod
    def attach_to_snapshot(cls, job: Job, snapshot: dict | None) -> dict:
        data = dict(snapshot or {})
        current_run = cls.current(job)
        if current_run.get("run_id"):
            data["run_id"] = current_run["run_id"]
            data["run_mode"] = current_run.get("mode")
        return data

    @classmethod
    def metadata_for_job(cls, job: Job, metadata: dict | None = None) -> dict:
        data = dict(metadata or {})
        current_run = cls.current(job)
        if current_run.get("run_id"):
            data.setdefault("run_id", current_run["run_id"])
            data.setdefault("run_mode", current_run.get("mode"))
        return data

    @classmethod
    def task_payload_for_job(cls, job: Job, payload: dict | None = None) -> dict:
        data = dict(payload or {})
        current_run = cls.current(job)
        if current_run.get("run_id"):
            data.setdefault("_run_id", current_run["run_id"])
            data.setdefault("_run_mode", current_run.get("mode"))
        return data

    @classmethod
    def run_matches_job(cls, job: Job, node_run: JobNodeRun | None) -> bool:
        run_id = cls.current_run_id(job)
        if not run_id:
            return True
        snapshot = node_run.input_snapshot if node_run else {}
        if not isinstance(snapshot, dict):
            return False
        return snapshot.get("run_id") == run_id

    @classmethod
    def query_current_node_runs(cls, job: Job):
        query = JobNodeRun.query.filter_by(job_id=job.id)
        run_id = cls.current_run_id(job)
        if run_id:
            query = query.filter(JobNodeRun.input_snapshot["run_id"].as_string() == run_id)
        return query
