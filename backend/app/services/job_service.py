import shutil
from pathlib import Path

from flask import current_app
from sqlalchemy import or_

from app.api import AppError
from app.extensions import db
from app.models import Artifact, Job, JobEvent, JobNodeRun, JobPromptRef, PromptVersion, Template
from app.services.artifact_service import ArtifactService
from app.services.error_detail_service import ErrorDetailService
from app.services.event_service import EventService
from app.services.job_run_state_service import JobRunStateService
from app.services.storage_service import StorageService
from app.services.workflow_service import WorkflowService
from app.services.workflow_validator import WorkflowValidator
from app.utils.ids import file_sha256, new_id
from app.utils.json_utils import to_jsonable

# Deferred import to avoid circular imports
def _get_prompt_service():
    from app.services.prompt_service import PromptService
    return PromptService


BRANCH_NODE_MAP = {
    "core": ["reverse_prompts", "rewrite_prompts", "export_manifest"],
    "t2v": ["submit_t2v", "poll_t2v"],
    "first_frame_image": ["submit_first_frame_image", "poll_first_frame_image"],
    "r2v_flash": ["reverse_prompts4r2v", "submit_r2v_flash", "poll_r2v_flash"],
    "i2v": ["submit_i2v", "poll_i2v"],
    "i2i_test": [
        "rewrite_t2i_to_i2i",
        "prepare_i2i_test_batch",
        "submit_i2i_test_image",
        "poll_i2i_test_image",
        "submit_i2i_test_i2v",
        "poll_i2i_test_i2v",
    ],
    "failure_agent": ["failure_agent"],
}


class JobService:
    @staticmethod
    def _normalize_job_name(value) -> str | None:
        if value is None:
            return None
        normalized = str(value).strip()
        return normalized or None

    @staticmethod
    def _ensure_unique_job_name(template: Template, job_name: str | None, exclude_job_pk: int | None = None) -> None:
        if not job_name:
            return
        query = Job.query.filter(Job.template_id == template.id, Job.job_name == job_name)
        if exclude_job_pk is not None:
            query = query.filter(Job.id != exclude_job_pk)
        if query.first():
            raise AppError(
                "JOB_NAME_EXISTS",
                "Job name already exists under this template",
                400,
            )

    @staticmethod
    def _expand_enabled_selection(value) -> set[str]:
        enabled = set()
        if isinstance(value, dict):
            for key, is_enabled in value.items():
                if is_enabled:
                    enabled.update(BRANCH_NODE_MAP.get(key, [key]))
        elif isinstance(value, list):
            for key in value:
                if isinstance(key, str):
                    enabled.update(BRANCH_NODE_MAP.get(key, [key]))
        return enabled

    @staticmethod
    def _expand_disabled_selection(value) -> set[str]:
        disabled = set()
        if isinstance(value, dict):
            for key, is_enabled in value.items():
                if not is_enabled:
                    disabled.update(BRANCH_NODE_MAP.get(key, [key]))
        elif isinstance(value, list):
            for key in value:
                if isinstance(key, str):
                    disabled.update(BRANCH_NODE_MAP.get(key, [key]))
        return disabled

    @staticmethod
    def _normalize_node_overrides(enabled_nodes, disabled_nodes, global_nodes=None) -> dict:
        user_enabled = JobService._expand_enabled_selection(enabled_nodes or [])
        user_disabled = JobService._expand_disabled_selection(enabled_nodes or [])
        user_disabled.update(JobService._expand_disabled_selection(disabled_nodes or []))
        if global_nodes is None:
            enabled = user_enabled
            disabled = user_disabled
        else:
            global_enabled = {node.node_key for node in global_nodes if node.enabled}
            global_disabled = {node.node_key for node in global_nodes if not node.enabled}
            enabled = (global_enabled - user_disabled) | user_enabled
            disabled = (global_disabled - user_enabled) | user_disabled
        return {
            "enabled_nodes": sorted(enabled),
            "disabled_nodes": sorted(disabled - enabled),
        }

    @staticmethod
    def _normalize_job_config(config: dict | None) -> dict:
        normalized = dict(config or {})
        models = dict(normalized.get("models") or {})
        node_models = {
            str(key): value
            for key, value in dict(normalized.get("node_models") or {}).items()
            if value
        }
        node_model_params = {
            str(key): dict(value)
            for key, value in dict(normalized.get("node_model_params") or {}).items()
            if isinstance(value, dict)
        }
        if models.get("i2v") and not models.get("main_i2v"):
            models["main_i2v"] = models["i2v"]
        i2i_test = dict(normalized.get("i2i_test") or {})
        if i2i_test.get("image_model") and not models.get("i2i_test_image"):
            models["i2i_test_image"] = i2i_test["image_model"]
        if i2i_test.get("i2v_model") and not models.get("i2i_test_i2v"):
            models["i2i_test_i2v"] = i2i_test["i2v_model"]
        normalized["models"] = models
        normalized["node_models"] = node_models
        normalized["node_model_params"] = node_model_params
        if i2i_test:
            normalized["i2i_test"] = i2i_test
        return normalized

    @staticmethod
    def _workflow_node_config_snapshot(global_nodes: list, enabled_nodes: list[str]) -> dict:
        enabled = set(enabled_nodes or [])
        snapshot = {}
        for node in global_nodes:
            if node.node_key not in enabled:
                continue
            config = dict(node.config or {})
            if config:
                snapshot[node.node_key] = to_jsonable(config)
        return snapshot

    @staticmethod
    def create_job(data: dict, source_video=None, initial_files: dict | None = None) -> Job:
        template_id = data.get("template_id") or "default"
        template = Template.query.filter_by(template_id=template_id).first()
        if not template and str(template_id).isdigit():
            template = db.session.get(Template, int(template_id))
        if not template:
            # Fall back to default template
            template = Template.query.filter_by(template_id="default").first()
        if not template:
            raise AppError("TEMPLATE_NOT_FOUND", "Template not found", 404)

        job_id = new_id("job")
        job_name = JobService._normalize_job_name(data.get("job_name"))
        JobService._ensure_unique_job_name(template, job_name)
        initial_files = initial_files or {}
        initial_prompts = data.get("initial_prompts") or {}
        initial_artifacts = data.get("initial_artifacts") or {}
        job_config = JobService._normalize_job_config(data.get("job_config") or {})
        source_info = {}
        if source_video:
            source_info = StorageService.save_source_video(source_video, job_id)
        elif data.get("source_video_path"):
            path = Path(data["source_video_path"])
            source_info = {
                "file_path": data["source_video_path"],
                "file_name": path.name,
                "source_hash": file_sha256(path) if path.exists() and path.is_file() else None,
            }
        elif initial_artifacts.get("source_video"):
            source_artifact = JobService._resolve_existing_artifact(initial_artifacts["source_video"])
            source_info = {
                "file_path": source_artifact.file_path,
                "file_name": source_artifact.file_name,
                "source_hash": None,
            }

        global_nodes = WorkflowService.list_nodes()
        node_overrides = JobService._normalize_node_overrides(
            data.get("enabled_nodes") or [],
            data.get("disabled_nodes") or [],
            global_nodes=global_nodes,
        )
        workflow_node_configs = JobService._workflow_node_config_snapshot(
            global_nodes,
            node_overrides["enabled_nodes"],
        )
        validation_artifacts = JobService._validation_artifacts(
            initial_artifacts, source_info, initial_files
        )
        if job_config.get("i2i_test_batch"):
            validation_artifacts["i2i_test_batch"] = True
        validation = WorkflowValidator.validate(
            enabled_nodes=node_overrides["enabled_nodes"],
            disabled_nodes=node_overrides["disabled_nodes"],
            initial_prompts=initial_prompts,
            initial_artifacts=validation_artifacts,
        )
        if not validation.get("valid"):
            errors = validation.get("errors") or []
            first = errors[0] if errors else {}
            raise AppError(
                first.get("code") or "DEPENDENCY_MISSING",
                first.get("message") or "Workflow dependencies are not satisfied",
                400,
                payload={"errors": errors},
            )
        if validation.get("required_inputs"):
            raise AppError(
                "MISSING_INPUT",
                "Missing required workflow inputs",
                400,
                payload={"required_inputs": validation["required_inputs"]},
            )

        job = Job(
            job_id=job_id,
            job_name=job_name,
            template_id=template.id,
            source_video_path=source_info.get("file_path"),
            source_file_name=source_info.get("file_name"),
            source_hash=source_info.get("source_hash"),
            status="pending",
            strategy=data.get("strategy") or "default",
            budget_limit=data.get("budget_limit"),
            node_overrides=node_overrides,
            config={
                **job_config,
                "workflow_node_configs": workflow_node_configs,
                "start_node": data.get("start_node"),
                "initial_prompts": initial_prompts,
                "initial_artifacts": validation_artifacts,
            },
        )
        db.session.add(job)
        db.session.flush()
        StorageService.job_dir(job.job_id, "raw")
        StorageService.job_dir(job.job_id, "outputs")
        StorageService.job_dir(job.job_id, "logs")
        EventService.record(
            job,
            "JOB_CREATED",
            message="Job created",
            payload={
                "template_id": template.template_id,
                "job_name": job.job_name,
                "source_video_path": job.source_video_path,
                "enabled_nodes": node_overrides["enabled_nodes"],
                "disabled_nodes": node_overrides["disabled_nodes"],
            },
        )

        if source_info.get("file_path"):
            ArtifactService.register_artifact(
                job,
                source_info["file_path"],
                "source_video",
                branch_key="source_video",
                metadata={"source": "upload" if source_video else "existing_or_path"},
            )

        prompt_refs = JobService._write_initial_prompts(job, template, initial_prompts)
        artifact_refs = JobService._write_initial_artifacts(
            job, initial_artifacts, initial_files
        )
        job.config = {
            **(job.config or {}),
            "initial_prompt_refs": prompt_refs,
            "initial_artifact_refs": artifact_refs,
        }

        db.session.commit()
        return job

    @staticmethod
    def _validation_artifacts(
        initial_artifacts: dict, source_info: dict, initial_files: dict
    ) -> dict:
        result = dict(initial_artifacts or {})
        if source_info.get("file_path"):
            result["source_video"] = result.get("source_video") or {"file_path": source_info["file_path"]}
        if initial_files.get("first_frame_image"):
            result["first_frame_image"] = result.get("first_frame_image") or {"uploaded": True}
        if initial_files.get("reference_images"):
            result["reference_images"] = result.get("reference_images") or {"uploaded": True}
        return result

    @staticmethod
    def _write_initial_prompts(job: Job, template: Template, initial_prompts: dict) -> dict:
        if not initial_prompts:
            return {}
        PromptService = _get_prompt_service()
        refs = {}
        for prompt_type, value in initial_prompts.items():
            normalized = JobService._resolve_initial_prompt(template, prompt_type, value)
            content = normalized.get("content", "").strip()
            if not content:
                continue
            prompt = PromptService.create_version_for_template(
                template,
                {
                    "prompt_type": prompt_type,
                    "prompt_key": normalized.get("prompt_key") or "default",
                    "job_id": job.job_id,
                    "title": normalized.get("title") or f"{prompt_type} (initial)",
                    "content": content,
                    "content_format": "markdown",
                    "source": normalized.get("source") or "manual",
                    "activate": True,
                },
            )
            db.session.flush()
            ref = PromptService.snapshot_for_job(job, prompt)
            refs[prompt_type] = {
                "prompt_id": prompt.prompt_id,
                "version": prompt.version,
                "ref_id": ref.ref_id,
                "prompt_key": prompt.prompt_key,
            }
        return refs

    @staticmethod
    def _resolve_initial_prompt(template: Template, prompt_type: str, value) -> dict:
        if isinstance(value, str):
            return {
                "content": value,
                "source": "manual",
                "prompt_key": "default",
            }
        if not isinstance(value, dict):
            return {}

        content = str(value.get("content") or "").strip()
        if content:
            return {
                "content": content,
                "source": value.get("source") or "manual",
                "prompt_key": value.get("prompt_key") or "default",
                "title": value.get("title"),
            }

        prompt = None
        prompt_id = value.get("prompt_id") or value.get("prompt_version_id")
        if prompt_id:
            prompt = PromptVersion.query.filter_by(prompt_id=str(prompt_id)).first()
            if not prompt and str(prompt_id).isdigit():
                prompt = db.session.get(PromptVersion, int(prompt_id))
        if not prompt and value.get("version"):
            query = PromptVersion.query.filter_by(
                template_id=template.id,
                prompt_type=prompt_type,
                prompt_key=value.get("prompt_key") or "default",
                version=value["version"],
            )
            prompt = query.order_by(PromptVersion.created_at.desc()).first()
        if not prompt:
            return {}
        return {
            "content": prompt.content,
            "source": value.get("source") or "existing_prompt",
            "prompt_key": value.get("prompt_key") or prompt.prompt_key or "default",
            "title": value.get("title") or f"{prompt_type} copied from {prompt.version}",
        }

    @staticmethod
    def _write_initial_artifacts(
        job: Job, initial_artifacts: dict, initial_files: dict
    ) -> dict:
        refs = {}
        first_frame_file = initial_files.get("first_frame_image")
        if first_frame_file:
            info = StorageService.save_reference_upload(first_frame_file, job.job_id)
            artifact = ArtifactService.register_artifact(
                job,
                info["file_path"],
                "first_frame_image",
                branch_key="first_frame_image",
                metadata={"source": "upload"},
            )
            refs["first_frame_image"] = [artifact.artifact_id]

        reference_files = initial_files.get("reference_images") or []
        for file_storage in reference_files:
            if not file_storage:
                continue
            info = StorageService.save_reference_upload(file_storage, job.job_id)
            artifact = ArtifactService.register_artifact(
                job,
                info["file_path"],
                "reference_image",
                branch_key="r2v_flash",
                metadata={"source": "upload"},
            )
            refs.setdefault("reference_images", []).append(artifact.artifact_id)

        for key, value in (initial_artifacts or {}).items():
            if key == "source_video":
                continue
            artifact_type = "reference_image" if key == "reference_images" else key
            branch_key = "r2v_flash" if key == "reference_images" else key
            for source_artifact in JobService._iter_existing_artifacts(value):
                artifact = ArtifactService.register_artifact(
                    job,
                    source_artifact.file_path,
                    artifact_type,
                    branch_key=branch_key,
                    model_id=source_artifact.model_id,
                    prompt_version=source_artifact.prompt_version,
                    metadata={
                        "source": "existing_artifact",
                        "source_artifact_id": source_artifact.artifact_id,
                        "source_job_id": source_artifact.job.job_id if source_artifact.job else None,
                    },
                )
                refs.setdefault(key, []).append(artifact.artifact_id)
        return refs

    @staticmethod
    def _resolve_existing_artifact(value) -> Artifact:
        artifact_id = None
        if isinstance(value, dict):
            artifact_id = value.get("artifact_id")
        elif isinstance(value, str):
            artifact_id = value
        if not artifact_id:
            raise AppError("ARTIFACT_NOT_FOUND", "Existing artifact id is required", 404)
        return ArtifactService.get_by_artifact_id(str(artifact_id))

    @staticmethod
    def _iter_existing_artifacts(value) -> list[Artifact]:
        values = []
        if isinstance(value, dict) and value.get("artifact_ids"):
            values.extend(value.get("artifact_ids") or [])
        elif isinstance(value, list):
            values.extend(value)
        else:
            values.append(value)

        artifacts = []
        for item in values:
            try:
                artifacts.append(JobService._resolve_existing_artifact(item))
            except AppError:
                if isinstance(item, dict) and item.get("source") == "upload":
                    continue
                raise
        return artifacts

    @staticmethod
    def list_jobs(params: dict) -> dict:
        page = max(int(params.get("page") or 1), 1)
        per_page = min(
            max(int(params.get("perPage") or params.get("per_page") or params.get("limit") or 20), 1),
            500,
        )
        query = Job.query

        status = (params.get("status") or "").strip()
        if status:
            query = query.filter(Job.status == status)

        node = (params.get("node") or "").strip()
        if node:
            query = query.filter(Job.current_node == node)

        search = (params.get("search") or "").strip()
        if search:
            query = query.filter(
                or_(
                    Job.job_id.contains(search),
                    Job.job_name.contains(search),
                )
            )

        template = (params.get("template") or params.get("template_id") or "").strip()
        series_id = (params.get("series_id") or params.get("series") or "").strip()
        if template or series_id:
            query = query.join(Template)
            if template:
                query = query.filter(
                    or_(Template.template_id == template, Template.name.contains(template))
                )
            if series_id:
                query = query.filter(Template.series == series_id)

        total = query.count()
        statuses = [
            "pending",
            "queued",
            "running",
            "success",
            "failed",
            "paused",
            "cancelled",
            "partial_success",
        ]
        status_counts = {
            status_key: Job.query.filter(Job.status == status_key).count()
            for status_key in statuses
        }
        jobs = (
            query.order_by(Job.created_at.desc())
            .offset((page - 1) * per_page)
            .limit(per_page)
            .all()
        )
        return {
            "jobs": [JobService._summary_dict(job) for job in jobs],
            "total": total,
            "page": page,
            "perPage": per_page,
            "status_counts": status_counts,
        }

    @staticmethod
    def _summary_dict(job: Job, total_nodes: int | None = None) -> dict:
        runs = JobService._visible_node_runs(job)
        data = job.to_dict()
        # Enrich with Series / Template display info (resolved via template)
        template = job.template
        data["template_name"] = template.name if template else None
        series_id = (template.series if template else None) or "default"
        data["series_id"] = series_id
        series = JobService._series_lookup().get(series_id)
        data["series_name"] = series.name if series else series_id
        all_nodes = WorkflowService.list_nodes()
        enabled_keys = {
            node.node_key for node in all_nodes if WorkflowService.is_node_enabled(job, node)
        }
        latest_by_node = {}
        for run in runs:
            latest_by_node[run.node_key] = run
        data["node_runs"] = [run.to_dict() for run in latest_by_node.values()]
        data["total_nodes"] = len(enabled_keys)
        completed_statuses = {"success", "failed", "skipped", "path_failed"}
        data["completed_nodes"] = len([
            run for key, run in latest_by_node.items()
            if key in enabled_keys and run.status in completed_statuses
        ])
        return data

    @staticmethod
    def _series_lookup() -> dict:
        """Cache-free per-call lookup of series_id -> Series for name resolution."""
        from app.models.series import Series
        return {s.series_id: s for s in Series.query.all()}

    @staticmethod
    def get_job(job_id: str) -> Job:
        job = Job.query.filter_by(job_id=job_id).first()
        if not job:
            raise AppError("JOB_NOT_FOUND", "Job not found", 404)
        return job

    @staticmethod
    def get_detail(job_id: str) -> dict:
        job = JobService.get_job(job_id)
        nodes = WorkflowService.list_nodes()
        latest_by_node = {}
        for run in JobService._visible_node_runs(job):
            latest_by_node[run.node_key] = run

        node_statuses = []
        for node in nodes:
            latest = latest_by_node.get(node.node_key)
            node_statuses.append(
                {
                    "node_key": node.node_key,
                    "display_name": node.display_name,
                    "sequence": node.sequence,
                    "branch_key": node.branch_key,
                    "enabled": WorkflowService.is_node_enabled(job, node),
                    "status": latest.status if latest else "pending",
                    "latest_run": latest.to_dict() if latest else None,
                }
            )

        events = (
            JobEvent.query.filter_by(job_id=job.id)
            .order_by(JobEvent.id.desc())
            .limit(100)
            .all()
        )
        events = list(reversed(events))
        enabled_keys = {
            node.node_key for node in nodes if WorkflowService.is_node_enabled(job, node)
        }
        return {
            "job": job.to_dict(),
            "node_runs": [run.to_dict() for run in latest_by_node.values()],
            "total_nodes": len(enabled_keys),
            "completed_nodes": len([
                run for key, run in latest_by_node.items()
                if key in enabled_keys and run.status in {"success", "failed", "skipped", "path_failed"}
            ]),
            "nodes": node_statuses,
            "artifacts": ArtifactService.list_for_job(job),
            "error_summary": job.error_summary,
            "error_detail": ErrorDetailService.latest_for_job(job),
            "recent_events": [event.to_dict() for event in events],
        }

    @staticmethod
    def _visible_node_runs(job: Job) -> list[JobNodeRun]:
        query = JobNodeRun.query.filter_by(job_id=job.id).order_by(
            JobNodeRun.created_at.asc()
        )
        current_run_id = JobRunStateService.current_run_id(job)
        if not current_run_id:
            return query.all()
        return [
            run
            for run in query.all()
            if isinstance(run.input_snapshot, dict)
            and run.input_snapshot.get("run_id") == current_run_id
        ]

    @staticmethod
    def update_job(job_id: str, data: dict) -> Job:
        job = JobService.get_job(job_id)
        if "job_name" in data:
            job_name = JobService._normalize_job_name(data.get("job_name"))
            JobService._ensure_unique_job_name(job.template, job_name, exclude_job_pk=job.id)
            job.job_name = job_name
        EventService.record(
            job,
            "JOB_UPDATED",
            message="Job updated",
            payload={"job_name": job.job_name},
        )
        db.session.commit()
        return job

    @staticmethod
    def delete_job(job_id: str, confirm_job_id: str) -> dict:
        job = JobService.get_job(job_id)
        confirmation = str(confirm_job_id or "").strip()
        accepted = {job.job_id}
        if job.job_name:
            accepted.add(job.job_name)
        if confirmation not in accepted:
            raise AppError(
                "INVALID_INPUT",
                "Job deletion confirmation does not match the Job ID or Job Name",
                400,
            )
        if job.status in {"running", "queued"}:
            raise AppError(
                "JOB_RUNNING",
                "Running or queued jobs cannot be deleted. Cancel or wait for completion first.",
                409,
            )

        deleted_job_id = job.job_id
        cleanup = JobService._delete_cleanup_snapshot(job)
        JobPromptRef.query.filter_by(job_id=job.id).delete(synchronize_session=False)
        PromptVersion.query.filter_by(job_id=job.id).delete(synchronize_session=False)
        db.session.delete(job)
        db.session.commit()
        storage_cleanup = JobService._cleanup_deleted_job_files(cleanup)
        return {
            "job_id": deleted_job_id,
            "deleted": True,
            "database_deleted": True,
            **storage_cleanup,
        }

    @staticmethod
    def _delete_cleanup_snapshot(job: Job) -> dict:
        return {
            "job_id": job.job_id,
            "source_video_path": job.source_video_path,
            "artifact_paths": [
                artifact.file_path for artifact in job.artifacts if artifact.file_path
            ],
        }

    @staticmethod
    def _cleanup_deleted_job_files(cleanup: dict) -> dict:
        job_id = cleanup["job_id"]
        root = StorageService.root()
        job_dir = (root / "jobs" / job_id).resolve()
        deleted_paths: list[str] = []
        errors: list[dict] = []
        try:
            if JobService._is_under(job_dir, root / "jobs") and job_dir.exists():
                shutil.rmtree(job_dir)
                deleted_paths.append(StorageService.relative_path(job_dir))
        except OSError as error:
            current_app.logger.warning("Failed to delete job directory %s: %s", job_dir, error)
            errors.append({"path": job_dir.as_posix(), "error": str(error)})

        candidates = set(cleanup.get("artifact_paths") or [])
        if cleanup.get("source_video_path"):
            candidates.add(cleanup["source_video_path"])
        for file_path in candidates:
            result = JobService._cleanup_deleted_job_file(job_id, file_path, job_dir)
            deleted_paths.extend(result["deleted_paths"])
            errors.extend(result["errors"])

        return {
            "storage_deleted": not errors,
            "deleted_storage_paths": sorted(set(deleted_paths)),
            "storage_errors": errors,
        }

    @staticmethod
    def _cleanup_deleted_job_file(job_id: str, file_path: str | None, job_dir: Path) -> dict:
        result = {"deleted_paths": [], "errors": []}
        if not file_path:
            return result
        root = StorageService.root()
        resolved = JobService._resolve_storage_cleanup_path(file_path)
        if not JobService._is_under(resolved, root):
            return result
        if JobService._is_under(resolved, root / "jobs" / job_id):
            return result
        if not resolved.exists():
            return result
        if not resolved.is_file():
            current_app.logger.warning("Skip deleting non-file job path outside job directory: %s", resolved)
            return result

        path_variants = JobService._storage_path_variants(file_path, resolved)
        if JobService._storage_path_is_still_referenced(path_variants):
            return result

        try:
            resolved.unlink()
            result["deleted_paths"].append(StorageService.relative_path(resolved))
        except OSError as error:
            current_app.logger.warning("Failed to delete job file %s: %s", resolved, error)
            result["errors"].append({"path": resolved.as_posix(), "error": str(error)})
        return result

    @staticmethod
    def _resolve_storage_cleanup_path(file_path: str | Path) -> Path:
        raw = Path(file_path)
        if raw.is_absolute():
            return raw.resolve()

        root = StorageService.root()
        direct = (root / raw).resolve()
        if direct.exists():
            return direct

        parts = raw.parts
        if parts and parts[0].lower() == root.name.lower():
            rooted = (root.parent / raw).resolve()
            if rooted.exists():
                return rooted
        return direct

    @staticmethod
    def _storage_path_variants(original_path: str | Path, resolved: Path) -> set[str]:
        root = StorageService.root()
        variants = {
            str(original_path),
            Path(original_path).as_posix(),
            str(resolved),
            resolved.as_posix(),
        }
        relative = StorageService.relative_path(resolved)
        relative_windows = relative.replace("/", "\\")
        variants.update(
            {
                relative,
                relative_windows,
                f"{root.name}/{relative}",
                f"{root.name}\\{relative_windows}",
            }
        )
        return {variant for variant in variants if variant}

    @staticmethod
    def _storage_path_is_still_referenced(path_variants: set[str]) -> bool:
        if Job.query.filter(Job.source_video_path.in_(path_variants)).first():
            return True
        if Artifact.query.filter(Artifact.file_path.in_(path_variants)).first():
            return True
        return False

    @staticmethod
    def _is_under(path: Path, root: Path) -> bool:
        try:
            path.resolve().relative_to(root.resolve())
            return True
        except ValueError:
            return False

    @staticmethod
    def pause(job_id: str) -> Job:
        job = JobService.get_job(job_id)
        job.status = "paused"
        EventService.record(job, "JOB_PAUSED", message="Job paused")
        db.session.commit()
        return job

    @staticmethod
    def cancel(job_id: str) -> Job:
        job = JobService.get_job(job_id)
        job.status = "cancelled"
        EventService.record(job, "JOB_CANCELLED", message="Job cancelled")
        db.session.commit()
        return job
