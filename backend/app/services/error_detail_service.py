import traceback
from typing import Any

from app.api import AppError
from app.models import ApiTask, Job, JobEvent, JobNodeRun
from app.utils.json_utils import to_jsonable


class ErrorDetailService:
    """Build compact, user-facing failure records for Job execution."""

    MAX_TEXT = 2400
    MAX_TRACEBACK = 6000
    MAX_DICT_ITEMS = 40
    MAX_LIST_ITEMS = 20

    HINTS = {
        "API_TASK_FAILED": "The remote model task failed or did not return the expected output.",
        "DEPENDENCY_MISSING": "A required upstream node, prompt, artifact, or API task is missing.",
        "PROMPT_NOT_FOUND": "A required active prompt was not found for this Job.",
        "MODEL_NOT_FOUND": "The configured model is missing or disabled.",
        "NODE_DISABLED": "The requested node is disabled for this Job.",
        "NODE_NOT_FOUND": "The workflow node could not be found.",
        "INTERNAL_ERROR": "The backend hit an unexpected error while executing the Job.",
    }

    @classmethod
    def build(
        cls,
        *,
        job: Job | None = None,
        node_run: JobNodeRun | None = None,
        code: str | None = None,
        message: str | None = None,
        error: Exception | None = None,
        payload: dict | None = None,
        extra: dict | None = None,
        include_traceback: bool | None = None,
    ) -> dict[str, Any]:
        error_code = code or getattr(error, "code", None) or "INTERNAL_ERROR"
        raw_message = message or getattr(error, "message", None) or str(error or "")
        summary = cls._truncate(str(raw_message or "Job failed"), 500)
        detail: dict[str, Any] = {
            "code": error_code,
            "summary": summary,
            "technical_message": cls._truncate(str(raw_message or ""), cls.MAX_TEXT),
            "hint": cls.HINTS.get(error_code),
        }
        if job:
            detail["job_id"] = job.job_id
        if node_run:
            detail.update(
                {
                    "node_key": node_run.node_key,
                    "run_id": node_run.run_id,
                    "attempt": node_run.attempt,
                }
            )
        task = cls._related_api_task(job, node_run)
        if task:
            detail["api_task"] = {
                "api_task_id": task.api_task_id,
                "provider_task_id": task.provider_task_id,
                "branch_key": task.branch_key,
                "model_id": task.model_id,
                "adapter_name": task.adapter_name,
                "status": task.status,
                "error_message": cls._truncate(task.error_message or "", 800),
            }
            if task.response_payload:
                detail["api_task"]["response"] = cls._compact(task.response_payload)

        raw_payload = payload
        if raw_payload is None and isinstance(error, AppError):
            raw_payload = error.payload
        if raw_payload:
            detail["payload"] = cls._compact(raw_payload)
        if extra:
            detail["extra"] = cls._compact(extra)

        should_trace = include_traceback
        if should_trace is None:
            should_trace = bool(error and not isinstance(error, AppError))
        if should_trace and error:
            detail["traceback"] = cls._truncate(
                "".join(traceback.format_exception(type(error), error, error.__traceback__)),
                cls.MAX_TRACEBACK,
            )
        return {key: value for key, value in detail.items() if value not in (None, "", {})}

    @classmethod
    def attach_to_node_run(
        cls,
        node_run: JobNodeRun | None,
        error_detail: dict[str, Any],
    ) -> None:
        if not node_run:
            return
        snapshot = node_run.output_snapshot if isinstance(node_run.output_snapshot, dict) else {}
        snapshot = dict(snapshot)
        snapshot["error_detail"] = error_detail
        node_run.output_snapshot = snapshot

    @classmethod
    def latest_for_job(cls, job: Job) -> dict[str, Any] | None:
        failed_run = (
            JobNodeRun.query.filter_by(job_id=job.id, status="failed")
            .order_by(JobNodeRun.created_at.desc())
            .first()
        )
        if failed_run:
            snapshot = failed_run.output_snapshot if isinstance(failed_run.output_snapshot, dict) else {}
            detail = snapshot.get("error_detail")
            if isinstance(detail, dict):
                return detail
            if failed_run.error_message:
                return cls.build(job=job, node_run=failed_run, message=failed_run.error_message)

        event = (
            JobEvent.query.filter_by(job_id=job.id, level="error")
            .order_by(JobEvent.created_at.desc())
            .first()
        )
        if event and isinstance(event.payload, dict):
            detail = event.payload.get("error_detail")
            if isinstance(detail, dict):
                return detail
        if job.error_summary:
            return cls.build(job=job, message=job.error_summary)
        return None

    @classmethod
    def _related_api_task(
        cls,
        job: Job | None,
        node_run: JobNodeRun | None,
    ) -> ApiTask | None:
        if node_run:
            task = (
                ApiTask.query.filter_by(node_run_id=node_run.id)
                .order_by(ApiTask.created_at.desc())
                .first()
            )
            if task:
                return task
        if job:
            return (
                ApiTask.query.filter_by(job_id=job.id)
                .order_by(ApiTask.created_at.desc())
                .first()
            )
        return None

    @classmethod
    def _compact(cls, value: Any, depth: int = 0) -> Any:
        value = to_jsonable(value)
        if depth >= 4:
            return cls._truncate(repr(value), 500)
        if isinstance(value, dict):
            items = list(value.items())
            compacted = {
                str(key): cls._compact(item, depth + 1)
                for key, item in items[: cls.MAX_DICT_ITEMS]
            }
            if len(items) > cls.MAX_DICT_ITEMS:
                compacted["_truncated_items"] = len(items) - cls.MAX_DICT_ITEMS
            return compacted
        if isinstance(value, list):
            compacted = [cls._compact(item, depth + 1) for item in value[: cls.MAX_LIST_ITEMS]]
            if len(value) > cls.MAX_LIST_ITEMS:
                compacted.append({"_truncated_items": len(value) - cls.MAX_LIST_ITEMS})
            return compacted
        if isinstance(value, str):
            return cls._truncate(value, cls.MAX_TEXT)
        if value is None or isinstance(value, (int, float, bool)):
            return value
        return cls._truncate(repr(value), cls.MAX_TEXT)

    @staticmethod
    def _truncate(value: str, limit: int) -> str:
        if len(value) <= limit:
            return value
        return f"{value[:limit]}... [truncated {len(value) - limit} chars]"
