from __future__ import annotations

from concurrent.futures import FIRST_COMPLETED, Future, ThreadPoolExecutor, wait
from dataclasses import dataclass
from http import HTTPStatus
from typing import Any

from flask import current_app

from app.api import AppError
from app.extensions import db
from app.models import Job, JobNodeRun, WorkflowNode
from app.services.error_detail_service import ErrorDetailService
from app.services.event_service import EventService
from app.services.node_runner import NodeRunner
from app.utils.time_utils import utc_now


@dataclass
class _WorkerResult:
    ok: bool
    node_key: str
    error_message: str | None = None
    error_code: str | None = None


class WorkflowScheduler:
    """DAG scheduler for one Job.

    The API layer already guarantees one scheduler thread per job_id. This
    class adds per-node workers inside that scheduler thread without sharing
    ORM objects across threads.
    """

    def __init__(self) -> None:
        self.app = current_app._get_current_object()
        self.max_workers = max(
            1, int(current_app.config.get("WORKFLOW_MAX_PARALLEL_NODES", 4))
        )
        self.max_poll_workers = max(
            1, int(current_app.config.get("WORKFLOW_MAX_PARALLEL_POLLS", 2))
        )
        self.running_node_keys: set[str] = set()

    def run(
        self,
        job: Job,
        nodes: list[WorkflowNode],
        force: bool,
        skip_scope_nodes: list[WorkflowNode] | None = None,
    ) -> dict:
        if job.status in {"cancelled"}:
            raise AppError(
                "INVALID_INPUT",
                "Cancelled job cannot be run",
                HTTPStatus.BAD_REQUEST,
            )

        nodes = sorted(nodes, key=lambda item: item.sequence or 0)
        skip_scope_nodes = sorted(
            skip_scope_nodes or [],
            key=lambda item: item.sequence or 0,
        )
        job_id = job.job_id
        job_pk = job.id
        active_keys = {node.node_key for node in nodes}
        node_by_key = {node.node_key: node for node in nodes}
        scope_node_by_key = {node.node_key: node for node in skip_scope_nodes}
        all_node_by_key = {
            node.node_key: node
            for node in WorkflowNode.query.filter_by(template_id=None).all()
        }
        all_node_by_key.update(scope_node_by_key)
        all_node_by_key.update(node_by_key)

        self._start_job(job)
        states: dict[str, str] = {}
        pending: set[str] = set()

        for node in skip_scope_nodes:
            if node.node_key in active_keys:
                continue
            self._record_skipped_if_needed(job, node, force, "node_disabled")
            states[node.node_key] = "skipped"

        for node in nodes:
            latest = self._latest_run(job_pk, node.node_key)
            if latest and latest.status == "success" and not force:
                self._record_skipped_if_needed(job, node, force, "already_success")
                states[node.node_key] = "skipped"
            else:
                states[node.node_key] = "pending"
                pending.add(node.node_key)

        had_failure = False
        stop_submitting = False
        futures: dict[Future, str] = {}

        with ThreadPoolExecutor(max_workers=self.max_workers) as executor:
            while pending or futures:
                job = db.session.get(Job, job_pk)
                if not job:
                    raise AppError("JOB_NOT_FOUND", "Job not found", 404)

                if job.status in {"paused", "cancelled"}:
                    stop_submitting = True

                if not stop_submitting:
                    submitted = self._submit_ready_nodes(
                        executor=executor,
                        job=job,
                        pending=pending,
                        states=states,
                        node_by_key=node_by_key,
                        all_node_by_key=all_node_by_key,
                        active_keys=active_keys,
                        force=force,
                        futures=futures,
                    )
                    if submitted:
                        continue

                    if pending and not futures:
                        blocked_key = self._first_blocked_node(
                            pending, node_by_key, states, all_node_by_key, active_keys, job
                        )
                        blocked = node_by_key[blocked_key]
                        missing = self._missing_dependencies(
                            job, blocked, states, all_node_by_key, active_keys
                        )
                        self._record_failed_before_run(
                            job,
                            blocked,
                            force,
                            f"Dependencies not satisfied: {', '.join(missing)}",
                        )
                        states[blocked_key] = "blocked"
                        pending.remove(blocked_key)
                        had_failure = True
                        stop_submitting = True
                        continue

                if not futures:
                    break

                db.session.commit()
                done, _ = wait(
                    list(futures.keys()),
                    timeout=1,
                    return_when=FIRST_COMPLETED,
                )
                for future in done:
                    node_key = futures.pop(future)
                    self.running_node_keys.discard(node_key)
                    result = self._future_result(node_key, future)
                    states[node_key] = "success" if result.ok else "failed"
                    self._update_current_nodes(job_pk)
                    if not result.ok:
                        had_failure = True
                        stop_submitting = True

        job = db.session.get(Job, job_pk)
        if job and job.status not in {"paused", "cancelled"}:
            job.status = "failed" if had_failure else "success"
            job.current_node = None
            if had_failure:
                error_detail = ErrorDetailService.latest_for_job(job)
                EventService.record(
                    job,
                    "JOB_FAILED",
                    message=job.error_summary or "Job failed",
                    payload={"error_detail": error_detail} if error_detail else {},
                    level="error",
                )
            else:
                job.error_summary = None
                EventService.record(job, "JOB_SUCCESS", message="Job execution completed")
            db.session.commit()

        return self._job_run_summary(job_pk)

    def _submit_ready_nodes(
        self,
        executor: ThreadPoolExecutor,
        job: Job,
        pending: set[str],
        states: dict[str, str],
        node_by_key: dict[str, WorkflowNode],
        all_node_by_key: dict[str, WorkflowNode],
        active_keys: set[str],
        force: bool,
        futures: dict[Future, str],
    ) -> bool:
        capacity = self.max_workers - len(futures)
        if capacity <= 0:
            return False

        running_polls = sum(1 for key in self.running_node_keys if self._is_poll_node(key))
        submitted = False
        ready = [
            node_by_key[key]
            for key in sorted(
                pending,
                key=lambda item: node_by_key[item].sequence or 0,
            )
            if self._dependencies_satisfied(
                job, node_by_key[key], states, all_node_by_key, active_keys
            )
        ]

        for node in ready:
            if capacity <= 0:
                break
            if self._is_poll_node(node.node_key) and running_polls >= self.max_poll_workers:
                continue

            node_run_id = self._declare_node_run(job, node, force)
            pending.remove(node.node_key)
            states[node.node_key] = "running"
            self.running_node_keys.add(node.node_key)
            self._update_current_nodes(job.id)

            future = executor.submit(
                self._run_node_worker,
                self.app,
                job.job_id,
                node.node_key,
                node_run_id,
                force,
            )
            futures[future] = node.node_key
            capacity -= 1
            submitted = True
            if self._is_poll_node(node.node_key):
                running_polls += 1

        return submitted

    def _start_job(self, job: Job) -> None:
        job.status = "running"
        EventService.record(
            job,
            "JOB_STARTED",
            message="Job execution started",
            payload={
                "scheduler": "dag_parallel",
                "max_workers": self.max_workers,
                "max_poll_workers": self.max_poll_workers,
            },
        )
        db.session.commit()

    def _declare_node_run(self, job: Job, node: WorkflowNode, force: bool) -> int:
        attempt = (
            JobNodeRun.query.filter_by(job_id=job.id, node_key=node.node_key).count() + 1
        )
        node_run = JobNodeRun(
            job_id=job.id,
            node_key=node.node_key,
            status="running",
            attempt=attempt,
            force=force,
            started_at=utc_now(),
        )
        node_run.input_snapshot = NodeRunner().build_input_snapshot(job, node)
        db.session.add(node_run)
        EventService.record(
            job,
            "NODE_STARTED",
            message=f"Node started: {node.node_key}",
            node_key=node.node_key,
            payload={"scheduler": "dag_parallel"},
        )
        db.session.commit()
        return node_run.id

    @staticmethod
    def _run_node_worker(
        app,
        job_id: str,
        node_key: str,
        node_run_id: int,
        force: bool,
    ) -> dict[str, Any]:
        with app.app_context():
            try:
                job = Job.query.filter_by(job_id=job_id).first()
                node = WorkflowNode.query.filter_by(
                    template_id=None, node_key=node_key
                ).first()
                node_run = db.session.get(JobNodeRun, node_run_id)
                if not job:
                    raise AppError("JOB_NOT_FOUND", "Job not found", 404)
                if not node or not node_run:
                    raise AppError("NODE_NOT_FOUND", f"Node not found: {node_key}", 404)

                output = NodeRunner().run(job, node, node_run)
                node_run.status = "success"
                node_run.output_snapshot = output or {}
                node_run.ended_at = utc_now()
                EventService.record(
                    job,
                    "NODE_SUCCESS",
                    message=f"Node succeeded: {node_key}",
                    node_key=node_key,
                )
                db.session.commit()
                return {"ok": True, "node_key": node_key}
            except AppError as error:
                WorkflowScheduler._safe_rollback()
                WorkflowScheduler._mark_worker_failed(
                    job_id,
                    node_run_id,
                    error.message,
                    error.code,
                    error=error,
                    payload=error.payload,
                )
                return {
                    "ok": False,
                    "node_key": node_key,
                    "error_message": error.message,
                    "error_code": error.code,
                }
            except Exception as error:
                WorkflowScheduler._safe_rollback()
                WorkflowScheduler._mark_worker_failed(
                    job_id,
                    node_run_id,
                    str(error),
                    "INTERNAL_ERROR",
                    error=error,
                )
                return {
                    "ok": False,
                    "node_key": node_key,
                    "error_message": str(error),
                    "error_code": "INTERNAL_ERROR",
                }
            finally:
                db.session.remove()

    @staticmethod
    def _safe_rollback() -> None:
        try:
            db.session.rollback()
        except Exception:
            db.session.remove()

    @staticmethod
    def _mark_worker_failed(
        job_id: str,
        node_run_id: int,
        message: str,
        code: str,
        error: Exception | None = None,
        payload: dict | None = None,
    ) -> None:
        db.session.remove()
        job = Job.query.filter_by(job_id=job_id).first()
        node_run = db.session.get(JobNodeRun, node_run_id)
        error_detail = ErrorDetailService.build(
            job=job,
            node_run=node_run,
            code=code,
            message=message,
            error=error,
            payload=payload,
            extra={"scheduler": "dag_parallel"},
        )
        if node_run:
            node_run.status = "failed"
            node_run.error_message = error_detail["summary"]
            node_run.ended_at = utc_now()
            ErrorDetailService.attach_to_node_run(node_run, error_detail)
        if job:
            if job.status not in {"paused", "cancelled"}:
                job.status = "failed"
            job.error_summary = error_detail["summary"]
            EventService.record(
                job,
                "NODE_FAILED",
                message=error_detail["summary"],
                node_key=node_run.node_key if node_run else None,
                payload={
                    "code": code,
                    "scheduler": "dag_parallel",
                    "error_detail": error_detail,
                },
                level="error",
            )
        db.session.commit()

    def _record_skipped_if_needed(
        self,
        job: Job,
        node: WorkflowNode,
        force: bool,
        reason: str,
    ) -> None:
        latest = self._latest_run(job.id, node.node_key)
        if latest and latest.status == "skipped" and not force:
            return
        run = JobNodeRun(
            job_id=job.id,
            node_key=node.node_key,
            status="skipped",
            attempt=JobNodeRun.query.filter_by(job_id=job.id, node_key=node.node_key).count() + 1,
            force=force,
            input_snapshot={"reason": reason},
            output_snapshot={"reason": reason},
            started_at=utc_now(),
            ended_at=utc_now(),
        )
        db.session.add(run)
        EventService.record(
            job,
            "NODE_SKIPPED",
            message=f"Node skipped: {node.node_key} ({reason})",
            node_key=node.node_key,
            payload={"reason": reason, "scheduler": "dag_parallel"},
        )
        db.session.commit()

    def _record_failed_before_run(
        self,
        job: Job,
        node: WorkflowNode,
        force: bool,
        message: str,
    ) -> None:
        run = JobNodeRun(
            job_id=job.id,
            node_key=node.node_key,
            status="failed",
            attempt=JobNodeRun.query.filter_by(job_id=job.id, node_key=node.node_key).count() + 1,
            force=force,
            input_snapshot={"depends_on": node.depends_on},
            output_snapshot={},
            error_message=message,
            started_at=utc_now(),
            ended_at=utc_now(),
        )
        db.session.add(run)
        db.session.flush()
        error_detail = ErrorDetailService.build(
            job=job,
            node_run=run,
            code="DEPENDENCY_MISSING",
            message=message,
            payload={"depends_on": node.depends_on},
            extra={"scheduler": "dag_parallel"},
        )
        run.error_message = error_detail["summary"]
        ErrorDetailService.attach_to_node_run(run, error_detail)
        job.status = "failed"
        job.error_summary = error_detail["summary"]
        EventService.record(
            job,
            "NODE_FAILED",
            message=error_detail["summary"],
            node_key=node.node_key,
            payload={
                "code": "DEPENDENCY_MISSING",
                "scheduler": "dag_parallel",
                "error_detail": error_detail,
            },
            level="error",
        )
        db.session.commit()

    def _dependencies_satisfied(
        self,
        job: Job,
        node: WorkflowNode,
        states: dict[str, str],
        all_node_by_key: dict[str, WorkflowNode],
        active_keys: set[str],
    ) -> bool:
        return not self._missing_dependencies(
            job, node, states, all_node_by_key, active_keys
        )

    def _missing_dependencies(
        self,
        job: Job,
        node: WorkflowNode,
        states: dict[str, str],
        all_node_by_key: dict[str, WorkflowNode],
        active_keys: set[str],
    ) -> list[str]:
        missing = []
        for dep_key in node.depends_on or []:
            dep_node = all_node_by_key.get(dep_key)
            if dep_node and not self._is_node_enabled(job, dep_node):
                continue
            if dep_key in active_keys:
                if states.get(dep_key) not in {"success", "skipped"}:
                    missing.append(dep_key)
                continue
            latest = self._latest_run(job.id, dep_key)
            if not latest or latest.status not in {"success", "skipped"}:
                missing.append(dep_key)
        return missing

    def _first_blocked_node(
        self,
        pending: set[str],
        node_by_key: dict[str, WorkflowNode],
        states: dict[str, str],
        all_node_by_key: dict[str, WorkflowNode],
        active_keys: set[str],
        job: Job,
    ) -> str:
        return min(
            pending,
            key=lambda key: (
                node_by_key[key].sequence or 0,
                len(self._missing_dependencies(
                    job, node_by_key[key], states, all_node_by_key, active_keys
                )),
                key,
            ),
        )

    @staticmethod
    def _future_result(node_key: str, future: Future) -> _WorkerResult:
        try:
            result = future.result()
            return _WorkerResult(
                ok=bool(result.get("ok")),
                node_key=result.get("node_key") or node_key,
                error_message=result.get("error_message"),
                error_code=result.get("error_code"),
            )
        except Exception as error:
            return _WorkerResult(
                ok=False,
                node_key=node_key,
                error_message=str(error),
                error_code="INTERNAL_ERROR",
            )

    def _update_current_nodes(self, job_pk: int) -> None:
        job = db.session.get(Job, job_pk)
        if not job or job.status in {"paused", "cancelled"}:
            return
        ordered = sorted(self.running_node_keys)
        if not ordered:
            job.current_node = None
        else:
            joined = ",".join(ordered)
            job.current_node = joined if len(joined) <= 120 else f"parallel:{len(ordered)}"
        db.session.commit()

    @staticmethod
    def _latest_run(job_pk: int, node_key: str) -> JobNodeRun | None:
        return (
            JobNodeRun.query.filter_by(job_id=job_pk, node_key=node_key)
            .order_by(JobNodeRun.created_at.desc())
            .first()
        )

    @staticmethod
    def _is_node_enabled(job: Job, node: WorkflowNode) -> bool:
        overrides = job.node_overrides or {}
        if node.node_key in set(overrides.get("disabled_nodes") or []):
            return False
        if node.node_key in set(overrides.get("enabled_nodes") or []):
            return True
        return bool(node.enabled)

    @staticmethod
    def _is_poll_node(node_key: str) -> bool:
        return str(node_key or "").startswith("poll_")

    @staticmethod
    def _job_run_summary(job_pk: int) -> dict:
        job = db.session.get(Job, job_pk)
        return {
            "job_id": job.job_id if job else None,
            "status": job.status if job else "failed",
            "current_node": job.current_node if job else None,
            "error_summary": job.error_summary if job else "Job not found",
            "node_runs": [
                run.to_dict()
                for run in JobNodeRun.query.filter_by(job_id=job_pk)
                .order_by(JobNodeRun.created_at.asc())
                .all()
            ],
        }
