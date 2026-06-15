from http import HTTPStatus

from flask import current_app

from app.api import AppError
from app.extensions import db
from app.models import Artifact, Job, JobNodeRun, PromptVersion, WorkflowNode
from app.services.error_detail_service import ErrorDetailService
from app.services.event_service import EventService
from app.services.job_run_state_service import JobRunStateService
from app.services.node_runner import NodeRunner
from app.services.prompt_sync_service import BUSINESS_PROMPT_TYPES, PromptSyncService
from app.services.workflow_validator import WorkflowValidator
from app.utils.time_utils import utc_now


class WorkflowService:
    @staticmethod
    def seed_default_nodes() -> int:
        created = 0
        for item in current_app.config["DEFAULT_WORKFLOW_NODES"]:
            existing = WorkflowNode.query.filter_by(
                template_id=None, node_key=item["node_key"]
            ).first()
            if existing:
                changed = False
                for field in ("display_name", "sequence", "branch_key", "depends_on"):
                    if getattr(existing, field) != item[field]:
                        setattr(existing, field, item[field])
                        changed = True
                if changed:
                    db.session.add(existing)
                continue
            node = WorkflowNode(**item)
            db.session.add(node)
            created += 1
        db.session.commit()
        return created

    @staticmethod
    def list_nodes() -> list[WorkflowNode]:
        if WorkflowNode.query.count() == 0:
            WorkflowService.seed_default_nodes()
        return WorkflowNode.query.filter_by(template_id=None).order_by(WorkflowNode.sequence.asc()).all()

    @staticmethod
    def get_node(node_key: str) -> WorkflowNode:
        node = WorkflowNode.query.filter_by(template_id=None, node_key=node_key).first()
        if not node:
            raise AppError("NODE_NOT_FOUND", "Workflow node not found", 404)
        return node

    @staticmethod
    def set_node_enabled(node_key: str, enabled: bool) -> WorkflowNode:
        node = WorkflowService.get_node(node_key)
        node.enabled = enabled
        db.session.commit()
        return node

    @staticmethod
    def update_node_config(node_key: str, config: dict) -> WorkflowNode:
        node = WorkflowService.get_node(node_key)
        current_config = dict(node.config or {})
        current_config.update(config or {})
        node.config = current_config
        db.session.commit()
        return node

    @staticmethod
    def run_full(job_id: str, force: bool = False) -> dict:
        job = WorkflowService._get_job(job_id)
        all_nodes = WorkflowService.list_nodes()
        nodes = [node for node in all_nodes if WorkflowService.is_node_enabled(job, node)]
        WorkflowService._validate_job_workflow(job)
        return WorkflowService._run_sequence(job, nodes, force=force, skip_scope_nodes=all_nodes)

    @staticmethod
    def run_from(job_id: str, node_key: str, force: bool = False) -> dict:
        job = WorkflowService._get_job(job_id)
        nodes = WorkflowService.list_nodes()
        keys = [node.node_key for node in nodes]
        if node_key not in keys:
            raise AppError("NODE_NOT_FOUND", "Workflow node not found", 404)
        start = keys.index(node_key)
        scoped_nodes = nodes[start:]
        active_nodes = [
            node for node in scoped_nodes if WorkflowService.is_node_enabled(job, node)
        ]
        WorkflowService._validate_job_workflow(job)
        return WorkflowService._run_sequence(
            job, active_nodes, force=force, skip_scope_nodes=scoped_nodes
        )

    @staticmethod
    def run_node(job_id: str, node_key: str, force: bool = False) -> dict:
        job = WorkflowService._get_job(job_id)
        node = WorkflowService.get_node(node_key)
        WorkflowService._validate_job_workflow(job)
        ok = WorkflowService._execute_node(job, node, force=force, explicit=True)
        db.session.refresh(job)
        if ok and job.status == "running":
            job.status = "partial_success"
            job.current_node = None
            EventService.record(
                job,
                "JOB_PARTIAL_SUCCESS",
                message=f"Single node completed: {node_key}",
                node_key=node_key,
            )
            db.session.commit()
        return WorkflowService._job_run_summary(job)

    @staticmethod
    def _get_job(job_id: str) -> Job:
        job = Job.query.filter_by(job_id=job_id).first()
        if not job:
            raise AppError("JOB_NOT_FOUND", "Job not found", 404)
        return job

    @staticmethod
    def _run_sequence(
        job: Job,
        nodes: list[WorkflowNode],
        force: bool,
        skip_scope_nodes: list[WorkflowNode] | None = None,
    ) -> dict:
        if current_app.config.get("WORKFLOW_PARALLEL_ENABLED", True):
            from app.services.workflow_scheduler import WorkflowScheduler

            return WorkflowScheduler().run(
                job,
                nodes,
                force=force,
                skip_scope_nodes=skip_scope_nodes,
            )

        if job.status in {"cancelled"}:
            raise AppError("INVALID_INPUT", "Cancelled job cannot be run", HTTPStatus.BAD_REQUEST)
        job.status = "running"
        EventService.record(job, "JOB_STARTED", message="Job execution started")
        db.session.commit()

        active_keys = {node.node_key for node in nodes}
        for node in skip_scope_nodes or []:
            if node.node_key in active_keys:
                continue
            latest = WorkflowService.latest_run(job, node.node_key)
            if latest and latest.status == "skipped" and not force:
                continue
            WorkflowService._record_skipped(job, node, force, "node_disabled")

        had_failure = False
        for node in nodes:
            db.session.refresh(job)
            if job.status in {"paused", "cancelled"}:
                break
            ok = WorkflowService._execute_node(job, node, force=force, explicit=False)
            if not ok:
                had_failure = True
                break

        db.session.refresh(job)
        if job.status not in {"paused", "cancelled"}:
            job.status = "failed" if had_failure else "success"
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
                EventService.record(job, "JOB_SUCCESS", message="Job execution completed")
            job.current_node = None
            db.session.commit()
        return WorkflowService._job_run_summary(job)

    @staticmethod
    def _execute_node(job: Job, node: WorkflowNode, force: bool, explicit: bool) -> bool:
        if not WorkflowService.is_node_enabled(job, node):
            if explicit:
                raise AppError("NODE_DISABLED", "Workflow node is disabled", 400)
            WorkflowService._record_skipped(job, node, force, "node_disabled")
            return True

        latest = WorkflowService.latest_run(job, node.node_key)
        if latest and latest.status == "success" and not force:
            WorkflowService._record_skipped(job, node, force, "already_success")
            return True

        missing = WorkflowService._missing_dependencies(job, node)
        if missing:
            WorkflowService._record_failed_before_run(
                job,
                node,
                force,
                f"Dependencies not satisfied: {', '.join(missing)}",
            )
            return False

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
        runner = NodeRunner()
        node_run.input_snapshot = runner.build_input_snapshot(job, node)
        job.status = "running"
        job.current_node = node.node_key
        db.session.add(node_run)
        EventService.record(
            job,
            "NODE_STARTED",
            message=f"Node started: {node.node_key}",
            node_key=node.node_key,
        )
        db.session.commit()

        try:
            output = runner.run(job, node, node_run)
            node_run.status = "success"
            node_run.output_snapshot = output or {}
            node_run.ended_at = utc_now()
            job.error_summary = None
            EventService.record(
                job,
                "NODE_SUCCESS",
                message=f"Node succeeded: {node.node_key}",
                node_key=node.node_key,
            )
            db.session.commit()
            return True
        except AppError as error:
            db.session.rollback()
            WorkflowService._mark_run_failed(
                job.id,
                node_run.id,
                error.message,
                error.code,
                error=error,
                payload=error.payload,
            )
            return False
        except Exception as error:
            db.session.rollback()
            WorkflowService._mark_run_failed(
                job.id,
                node_run.id,
                str(error),
                "INTERNAL_ERROR",
                error=error,
            )
            return False

    @staticmethod
    def _mark_run_failed(
        job_pk: int,
        node_run_pk: int,
        message: str,
        code: str,
        error: Exception | None = None,
        payload: dict | None = None,
    ) -> None:
        job = db.session.get(Job, job_pk)
        node_run = db.session.get(JobNodeRun, node_run_pk)
        error_detail = ErrorDetailService.build(
            job=job,
            node_run=node_run,
            code=code,
            message=message,
            error=error,
            payload=payload,
        )
        node_run.status = "failed"
        node_run.error_message = error_detail["summary"]
        node_run.ended_at = utc_now()
        ErrorDetailService.attach_to_node_run(node_run, error_detail)
        job.status = "failed"
        job.error_summary = error_detail["summary"]
        EventService.record(
            job,
            "NODE_FAILED",
            message=error_detail["summary"],
            node_key=node_run.node_key,
            payload={"code": code, "error_detail": error_detail},
            level="error",
        )
        db.session.commit()

    @staticmethod
    def _record_skipped(job: Job, node: WorkflowNode, force: bool, reason: str) -> None:
        run = JobNodeRun(
            job_id=job.id,
            node_key=node.node_key,
            status="skipped",
            attempt=JobNodeRun.query.filter_by(job_id=job.id, node_key=node.node_key).count() + 1,
            force=force,
            input_snapshot=JobRunStateService.attach_to_snapshot(job, {"reason": reason}),
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
            payload={"reason": reason},
        )
        db.session.commit()

    @staticmethod
    def _record_failed_before_run(job: Job, node: WorkflowNode, force: bool, message: str) -> None:
        run = JobNodeRun(
            job_id=job.id,
            node_key=node.node_key,
            status="failed",
            attempt=JobNodeRun.query.filter_by(job_id=job.id, node_key=node.node_key).count() + 1,
            force=force,
            input_snapshot=JobRunStateService.attach_to_snapshot(
                job, {"depends_on": node.depends_on}
            ),
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
            payload={"code": "DEPENDENCY_MISSING", "error_detail": error_detail},
            level="error",
        )
        db.session.commit()

    @staticmethod
    def is_node_enabled(job: Job, node: WorkflowNode) -> bool:
        overrides = job.node_overrides or {}
        if node.node_key in set(overrides.get("disabled_nodes") or []):
            return False
        if node.node_key in set(overrides.get("enabled_nodes") or []):
            return True
        return bool(node.enabled)

    @staticmethod
    def latest_run(job: Job, node_key: str) -> JobNodeRun | None:
        query = JobNodeRun.query.filter_by(job_id=job.id, node_key=node_key)
        current_run_id = JobRunStateService.current_run_id(job)
        if current_run_id:
            run = (
                query.filter(JobNodeRun.input_snapshot["run_id"].as_string() == current_run_id)
                .order_by(JobNodeRun.created_at.desc())
                .first()
            )
            if run:
                return run
            return None
        return query.order_by(JobNodeRun.created_at.desc()).first()

    @staticmethod
    def _missing_dependencies(job: Job, node: WorkflowNode) -> list[str]:
        missing = []
        for dep_key in node.depends_on or []:
            dep_node = WorkflowNode.query.filter_by(template_id=None, node_key=dep_key).first()
            if dep_node and not WorkflowService.is_node_enabled(job, dep_node):
                continue
            latest = WorkflowService.latest_run(job, dep_key)
            if not latest or latest.status not in {"success", "skipped"}:
                missing.append(dep_key)
        return missing

    @staticmethod
    def _validate_job_workflow(job: Job) -> None:
        all_nodes = WorkflowService.list_nodes()
        enabled_nodes = [
            node.node_key for node in all_nodes if WorkflowService.is_node_enabled(job, node)
        ]
        active_keys = set(enabled_nodes)
        disabled_nodes = [node.node_key for node in all_nodes if node.node_key not in active_keys]
        initial_artifacts = {}
        if job.source_video_path:
            initial_artifacts["source_video"] = True
        if Artifact.query.filter_by(job_id=job.id, artifact_type="first_frame_image").first():
            initial_artifacts["first_frame_image"] = True
        if Artifact.query.filter_by(job_id=job.id, artifact_type="reference_image").first():
            initial_artifacts["reference_images"] = True
        if Artifact.query.filter_by(job_id=job.id, artifact_type="i2i_test_first_frame_image").first():
            initial_artifacts["i2i_test_first_frame_image"] = True
        if (job.config or {}).get("i2i_test_batch"):
            initial_artifacts["i2i_test_batch"] = True
        initial_artifacts.update((job.config or {}).get("initial_artifacts") or {})
        initial_prompts = dict((job.config or {}).get("initial_prompts") or {})
        for prompt_type in BUSINESS_PROMPT_TYPES:
            if prompt_type not in initial_prompts and WorkflowService._has_usable_active_prompt(job, prompt_type):
                initial_prompts[prompt_type] = {"existing_prompt": True}
        result = WorkflowValidator.validate(
            enabled_nodes=enabled_nodes,
            disabled_nodes=disabled_nodes,
            initial_prompts=initial_prompts,
            initial_artifacts=initial_artifacts,
        )
        if not result.get("valid"):
            errors = result.get("errors") or []
            first = errors[0] if errors else {}
            raise AppError(
                first.get("code") or "DEPENDENCY_MISSING",
                first.get("message") or "Workflow dependencies are not satisfied",
                400,
                payload={"errors": errors},
            )
        if result.get("required_inputs"):
            raise AppError(
                "MISSING_INPUT",
                "Missing required workflow inputs",
                400,
                payload={"required_inputs": result["required_inputs"]},
            )

    @staticmethod
    def _has_usable_active_prompt(job: Job, prompt_type: str) -> bool:
        job_prompt = (
            PromptVersion.query.filter_by(
                template_id=job.template_id,
                job_id=job.id,
                prompt_type=prompt_type,
                prompt_key="default",
                is_active=True,
            )
            .order_by(PromptVersion.created_at.desc())
            .first()
        )
        if PromptSyncService.is_usable_business_prompt(job_prompt):
            return True
        template_prompt = (
            PromptVersion.query.filter_by(
                template_id=job.template_id,
                prompt_type=prompt_type,
                prompt_key="default",
                is_active=True,
            )
            .filter(PromptVersion.job_id.is_(None))
            .order_by(PromptVersion.created_at.desc())
            .first()
        )
        return PromptSyncService.is_usable_business_prompt(template_prompt)

    @staticmethod
    def _job_run_summary(job: Job) -> dict:
        return {
            "job_id": job.job_id,
            "status": job.status,
            "current_node": job.current_node,
            "error_summary": job.error_summary,
            "node_runs": [
                run.to_dict()
                for run in JobRunStateService.query_current_node_runs(job)
                .order_by(JobNodeRun.created_at.asc())
                .all()
            ],
        }
