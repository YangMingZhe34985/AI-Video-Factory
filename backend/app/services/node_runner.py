import json
import random
import time
from pathlib import Path

from flask import current_app

from app.adapters import get_adapter
from app.api import AppError
from app.extensions import db
from app.models import ApiTask, Artifact, Job, JobNodeRun, JobPromptRef, ModelRegistry, PromptVersion
from app.services.artifact_service import ArtifactService
from app.services.event_service import EventService
from app.services.i2i_test_batch_service import I2ITestBatchService
from app.services.job_run_state_service import JobRunStateService
from app.services.model_service import ModelService
from app.services.prompt_service import PromptService
from app.services.prompt_sync_service import PromptSyncService
from app.services.storage_service import StorageService
from app.services.video_compression_service import VideoCompressionService
from app.utils.time_utils import utc_now


class NodeRunner:
    PROMPT_FILE_NAMES = {
        "t2v": "reverse_t2v.md",
        "first_frame_image": "first_frame_image.md",
        "i2v": "i2v.md",
        "r2v_flash": "r2v_flash.md",
        "i2i": "i2i.md",
    }

    USER_EDIT_SOURCES = {"manual", "edit", "rollback"}

    def build_input_snapshot(self, job: Job, node) -> dict:
        return JobRunStateService.attach_to_snapshot(job, {
            "job_id": job.job_id,
            "template_id": job.external_template_id,
            "node_key": node.node_key,
            "branch_key": node.branch_key,
            "source_video_path": job.source_video_path,
            "strategy": job.strategy,
            "depends_on": node.depends_on,
            "node_config": self._node_config(job, node),
            "job_config": job.config,
        })

    def run(self, job: Job, node, node_run: JobNodeRun) -> dict:
        handler = getattr(self, f"_run_{node.node_key}", None)
        if handler is None:
            raise AppError("NODE_NOT_FOUND", f"Node handler not found: {node.node_key}", 404)
        return handler(job, node, node_run)

    def _get_model(self, model_id: str) -> ModelRegistry:
        try:
            return ModelService.get_model(model_id, require_enabled=True)
        except AppError as error:
            if error.code != "MODEL_NOT_FOUND":
                raise
            ModelService.seed_defaults()
            return ModelService.get_model(model_id, require_enabled=True)

    def _model_for(self, job: Job, node, key: str, default_config_key: str) -> ModelRegistry:
        job_config = job.config or {}
        node_key = node.node_key if node else None
        node_model = self._node_config(job, node).get("model_id") if node else None
        node_override = (job_config.get("node_models") or {}).get(node_key)
        configured = (job_config.get("models") or {}).get(key)
        model_id = node_override or configured or node_model or current_app.config[default_config_key]
        return self._get_model(model_id)

    def _model_for_any(
        self,
        job: Job,
        node,
        keys: list[str],
        default_config_key: str,
    ) -> ModelRegistry:
        job_config = job.config or {}
        node_key = node.node_key if node else None
        node_model = self._node_config(job, node).get("model_id") if node else None
        node_override = (job_config.get("node_models") or {}).get(node_key)
        models = job_config.get("models") or {}
        configured = next((models.get(key) for key in keys if models.get(key)), None)
        model_id = node_override or configured or node_model or current_app.config[default_config_key]
        return self._get_model(model_id)

    def _adapter_payload(
        self,
        model: ModelRegistry,
        inputs: dict,
        params: dict | None = None,
        job: Job | None = None,
        node=None,
        param_key: str | None = None,
    ):
        adapter = get_adapter(model.adapter_name, model=model)
        merged_params = dict(model.default_params or {})
        node_key = node.node_key if node else None
        node_config = self._node_config(job, node) if node else {}
        if node_config:
            merged_params.update(node_config.get("model_params") or {})
        if job and param_key:
            merged_params.update(((job.config or {}).get("model_params") or {}).get(param_key) or {})
        if job and node_key:
            merged_params.update(((job.config or {}).get("node_model_params") or {}).get(node_key) or {})
        merged_params.update(params or {})
        payload = adapter.build_payload(inputs, merged_params)
        self._release_db_connection()
        try:
            response = adapter.submit(payload)
        except AppError as error:
            enriched_payload = dict(error.payload or {})
            enriched_payload.update(
                {
                    "model_id": model.model_id,
                    "adapter_name": model.adapter_name,
                    "task_type": model.task_type,
                    "request_payload": payload,
                    "node_key": node_key,
                    "param_key": param_key,
                }
            )
            raise AppError(
                error.code,
                error.message,
                error.status_code,
                payload=enriched_payload,
            ) from error
        return adapter, payload, response

    def _i2i_test_image_adapter_payload(
        self,
        model: ModelRegistry,
        inputs: dict,
        job: Job | None = None,
        node=None,
        param_key: str | None = None,
    ):
        """Like _adapter_payload but selects the correct adapter for I2I test images.

        wan2.7-image is a multimodal model that requires the multimodal-generation
        endpoint and a synchronous call.  All other image models continue to use
        the standard dashscope_image adapter via _adapter_payload.

        Returns (adapter, effective_adapter_name, payload, response).
        """
        from app.adapters.dashscope_multimodal_image import DashScopeMultimodalSyncAdapter

        if model.model_id.startswith("wan2.7-image"):
            adapter = DashScopeMultimodalSyncAdapter(model=model)
            effective_adapter_name = "dashscope_multimodal_sync"
        else:
            adapter = get_adapter(model.adapter_name, model=model)
            effective_adapter_name = model.adapter_name

        merged_params = dict(model.default_params or {})
        node_key = node.node_key if node else None
        node_config = self._node_config(job, node) if node else {}
        if node_config:
            merged_params.update(node_config.get("model_params") or {})
        if job and param_key:
            merged_params.update(((job.config or {}).get("model_params") or {}).get(param_key) or {})
        if job and node_key:
            merged_params.update(((job.config or {}).get("node_model_params") or {}).get(node_key) or {})

        payload = adapter.build_payload(inputs, merged_params)
        self._release_db_connection()
        try:
            response = adapter.submit(payload)
        except AppError as error:
            enriched = dict(error.payload or {})
            enriched.update({
                "model_id": model.model_id,
                "adapter_name": effective_adapter_name,
                "request_payload": payload,
                "node_key": node_key,
                "param_key": param_key,
            })
            raise AppError(error.code, error.message, error.status_code, payload=enriched) from error
        return adapter, effective_adapter_name, payload, response

    def _negative_prompt(self, job: Job) -> str | None:
        """Return the effective negative prompt for generation nodes.

        Priority: job.config["negative_prompt"] override → DEFAULT_NEGATIVE_PROMPT.
        Returns None when the resolved value is empty (suppresses the field).
        """
        job_override = (job.config or {}).get("negative_prompt")
        if job_override is not None:
            return job_override or None
        default = current_app.config.get("DEFAULT_NEGATIVE_PROMPT") or ""
        return default or None

    @staticmethod
    def _node_config(job: Job | None, node) -> dict:
        if not node:
            return {}
        if job:
            snapshot = ((job.config or {}).get("workflow_node_configs") or {}).get(node.node_key)
            if isinstance(snapshot, dict):
                return snapshot
        return dict(node.config or {})

    @staticmethod
    def _release_db_connection() -> None:
        try:
            db.session.commit()
        except Exception:
            db.session.rollback()
            raise
        finally:
            db.session.close()

    @staticmethod
    def _render_prompt_template(template: str, **values) -> str:
        rendered = template or ""
        for key, value in values.items():
            rendered = rendered.replace(f"{{{{{key}}}}}", str(value))
        return rendered.strip()

    @staticmethod
    def _schema_for(keys: list[str]) -> dict:
        return {
            "type": "object",
            "properties": {key: {"type": "string"} for key in keys},
            "required": keys,
            "additionalProperties": False,
        }

    @staticmethod
    def _strict_json_response(response: dict, required_keys: list[str]) -> dict:
        data = response.get("json")
        if not isinstance(data, dict):
            raise AppError(
                "API_TASK_FAILED",
                "Model response did not include a JSON object",
                502,
                payload={"response": response},
            )
        missing = [key for key in required_keys if not str(data.get(key) or "").strip()]
        if missing:
            raise AppError(
                "API_TASK_FAILED",
                f"Model response missing required JSON fields: {', '.join(missing)}",
                502,
                payload={"response": response, "missing": missing},
            )
        return {key: str(data[key]).strip() for key in required_keys}

    @staticmethod
    def _text_prompt_response(response: dict, fallback_json_key: str) -> str:
        text = str(response.get("content") or "").strip()
        parsed = NodeRunner._json_field_from_text(text, fallback_json_key)
        if parsed:
            return parsed
        if text:
            return text

        data = response.get("json")
        if isinstance(data, dict) and str(data.get(fallback_json_key) or "").strip():
            return str(data[fallback_json_key]).strip()
        raise AppError(
            "API_TASK_FAILED",
            "Model response did not include prompt text",
            502,
            payload={"response": response},
        )

    @staticmethod
    def _json_field_from_text(text: str, key: str) -> str | None:
        cleaned = (text or "").strip()
        if not cleaned:
            return None
        if cleaned.startswith("```"):
            lines = cleaned.splitlines()
            if lines and lines[0].strip().startswith("```"):
                lines = lines[1:]
            if lines and lines[-1].strip().startswith("```"):
                lines = lines[:-1]
            cleaned = "\n".join(lines).strip()
        try:
            data = json.loads(cleaned)
        except json.JSONDecodeError:
            return None
        if isinstance(data, dict) and str(data.get(key) or "").strip():
            return str(data[key]).strip()
        return None

    def _poll_until_complete(self, adapter, task: ApiTask) -> dict:
        max_rounds = int(current_app.config.get("MAX_POLL_ROUNDS", 90))
        interval = int(current_app.config.get("POLL_INTERVAL_SEC", 10))
        rounds = max(max_rounds, 1)
        provider_task_id = task.provider_task_id
        response = {}
        for index in range(rounds):
            self._release_db_connection()
            response = adapter.poll(provider_task_id)
            status = response.get("status")
            if status in {"success", "failed", "cancelled"}:
                return response
            if index < rounds - 1:
                self._release_db_connection()
                time.sleep(interval)
        response["status"] = "running"
        return response

    def _complete_task_from_adapter(
        self,
        job: Job,
        node_run: JobNodeRun,
        task: ApiTask,
        adapter,
        response: dict,
        artifact_type: str,
        prompt_version: str | None = None,
        metadata: dict | None = None,
        artifact_branch_key: str | None = None,
    ) -> Artifact:
        status = response.get("status")
        task.response_payload = response
        if status != "success":
            task.status = status or "failed"
            task.error_message = response.get("error_message") or f"Task is not complete: {status}"
            raise AppError("API_TASK_FAILED", task.error_message, 502, payload=response)

        expected_path = StorageService.resolve(task.expected_artifact_path)
        response = dict(response)
        response["expected_output_path"] = str(expected_path)
        output_files = adapter.download_outputs(response, str(expected_path.parent))
        if not output_files:
            raise AppError(
                "API_TASK_FAILED",
                "Model task succeeded but no downloadable output was found",
                502,
                payload=response,
            )
        downloaded = Path(output_files[0])
        artifact_metadata = dict(metadata or {})
        registered_path = downloaded
        if self._is_video_artifact(artifact_type):
            registered_path, compression = self._compress_video_artifact(
                job, node_run, downloaded, artifact_type
            )
            artifact_metadata["compression"] = compression
        file_path = StorageService.relative_path(registered_path)
        task.status = "success"
        task.response_payload = response
        task.completed_at = utc_now()
        EventService.record(
            job,
            "API_TASK_COMPLETED",
            message=f"API task completed: {task.branch_key}",
            node_key=node_run.node_key,
            payload={"api_task_id": task.api_task_id},
        )
        return ArtifactService.register_artifact(
            job,
            file_path,
            artifact_type,
            branch_key=artifact_branch_key or task.branch_key,
            node_run=node_run,
            api_task=task,
            model_id=task.model_id,
            prompt_version=prompt_version,
            metadata=artifact_metadata,
        )

    def _is_video_artifact(self, artifact_type: str) -> bool:
        return "video" in str(artifact_type or "")

    def _compress_video_artifact(
        self,
        job: Job,
        node_run: JobNodeRun,
        downloaded: Path,
        artifact_type: str,
    ) -> tuple[Path, dict]:
        selected_path, metadata = VideoCompressionService.compress_for_artifact(downloaded)
        status = metadata.get("status")
        if status == "success":
            EventService.record(
                job,
                "VIDEO_COMPRESSED",
                message=f"Video compressed: {artifact_type}",
                node_key=node_run.node_key,
                payload={
                    "artifact_type": artifact_type,
                    "original_file_path": metadata.get("original_file_path"),
                    "compressed_file_path": metadata.get("compressed_file_path"),
                    "original_size": metadata.get("original_size"),
                    "compressed_size": metadata.get("compressed_size"),
                },
            )
        elif metadata.get("enabled") and status not in {"disabled", "skipped_already_compressed"}:
            EventService.record(
                job,
                "VIDEO_COMPRESSION_SKIPPED",
                message=f"Video compression skipped: {status}",
                node_key=node_run.node_key,
                level="warning",
                payload={"artifact_type": artifact_type, "compression": metadata},
            )
        return selected_path, metadata

    def _write_json_artifact(
        self,
        job: Job,
        node_run: JobNodeRun,
        relative_parts: list[str],
        payload: dict,
        artifact_type: str,
        branch_key: str,
        model_id: str | None = None,
        prompt_version: str | None = None,
        api_task: ApiTask | None = None,
    ) -> str:
        path = StorageService.write_job_json(job.job_id, relative_parts, payload)
        ArtifactService.register_artifact(
            job,
            path,
            artifact_type,
            branch_key=branch_key,
            node_run=node_run,
            api_task=api_task,
            model_id=model_id,
            prompt_version=prompt_version,
        )
        return path

    def _write_prompt_files_for_created(
        self,
        job: Job,
        node_run: JobNodeRun,
        prompts: list[PromptVersion],
        source_node: str,
    ) -> dict:
        db.session.flush()
        prompt_artifacts = [
            self._write_prompt_markdown_artifact(job, node_run, prompt, source_node)
            for prompt in prompts
        ]
        summary_artifact = self._write_prompt_summary_artifact(job, node_run)
        return {
            "prompt_artifacts": [artifact.to_dict() for artifact in prompt_artifacts],
            "prompt_summary_artifact": summary_artifact.to_dict(),
        }

    def _write_prompt_markdown_artifact(
        self,
        job: Job,
        node_run: JobNodeRun,
        prompt: PromptVersion,
        source_node: str,
    ) -> Artifact:
        path = StorageService.write_text_artifact(
            job.job_id,
            self._prompt_relative_parts(job, self._prompt_file_name(prompt)),
            prompt.content,
        )
        return ArtifactService.register_artifact(
            job,
            path,
            "prompt_markdown",
            branch_key=prompt.prompt_type,
            node_run=node_run,
            prompt_version=prompt.version,
            metadata={
                "prompt_id": prompt.prompt_id,
                "prompt_type": prompt.prompt_type,
                "prompt_key": prompt.prompt_key,
                "version": prompt.version,
                "source_node": source_node,
                "content_format": prompt.content_format,
            },
        )

    def _write_prompt_summary_artifact(self, job: Job, node_run: JobNodeRun) -> Artifact:
        refs = (
            JobPromptRef.query.filter_by(job_id=job.id)
            .order_by(JobPromptRef.created_at.asc())
            .all()
        )
        prompt_files = (
            Artifact.query.filter_by(job_id=job.id, artifact_type="prompt_markdown")
            .order_by(Artifact.created_at.asc())
            .all()
        )
        file_map = {
            (artifact.branch_key, artifact.prompt_version): artifact for artifact in prompt_files
        }
        summary = {
            "job_id": job.job_id,
            "template_id": job.external_template_id,
            "generated_at": utc_now().isoformat(),
            "prompts": [
                self._prompt_summary_item(ref, file_map.get((ref.prompt_type, ref.version)))
                for ref in refs
            ],
        }
        path = StorageService.write_job_json(
            job.job_id,
            self._prompt_relative_parts(job, "prompt_summary.json"),
            summary,
        )
        return ArtifactService.register_artifact(
            job,
            path,
            "prompt_summary",
            branch_key="prompts",
            node_run=node_run,
            metadata={"prompt_count": len(summary["prompts"])},
        )

    @staticmethod
    def _prompt_summary_item(ref: JobPromptRef, artifact: Artifact | None) -> dict:
        return {
            "prompt_type": ref.prompt_type,
            "prompt_key": ref.prompt_key,
            "version": ref.version,
            "title": ref.title,
            "file_path": artifact.file_path if artifact else None,
            "artifact_id": artifact.artifact_id if artifact else None,
            "source_node": (artifact.meta or {}).get("source_node") if artifact else None,
        }

    @classmethod
    def _prompt_file_name(cls, prompt: PromptVersion) -> str:
        base = cls.PROMPT_FILE_NAMES.get(prompt.prompt_type, f"{prompt.prompt_type}.md")
        if not prompt.prompt_key or prompt.prompt_key == "default":
            return base
        stem = Path(base).stem
        suffix = Path(base).suffix or ".md"
        return f"{stem}_{cls._safe_prompt_file_part(prompt.prompt_key)}{suffix}"

    @staticmethod
    def _safe_prompt_file_part(value: str) -> str:
        cleaned = "".join(char if char.isalnum() or char in {"-", "_"} else "_" for char in str(value))
        return cleaned.strip("_") or "default"

    @staticmethod
    def _prompt_relative_parts(job: Job, file_name: str) -> list[str]:
        run_id = JobRunStateService.current_run_id(job)
        if run_id:
            return ["prompts", run_id, file_name]
        return ["prompts", file_name]

    def _create_api_task(
        self,
        job: Job,
        node_run: JobNodeRun,
        branch_key: str,
        model: ModelRegistry,
        request_payload: dict,
        response_payload: dict,
        expected_artifact_path: str,
        adapter_name: str | None = None,
    ) -> ApiTask:
        task = ApiTask(
            job_id=job.id,
            node_run_id=node_run.id,
            branch_key=branch_key,
            model_id=model.model_id,
            adapter_name=adapter_name or model.adapter_name,
            provider_task_id=response_payload.get("provider_task_id"),
            status="submitted",
            request_payload=JobRunStateService.task_payload_for_job(job, request_payload),
            response_payload=response_payload,
            expected_artifact_path=expected_artifact_path,
            submitted_at=utc_now(),
        )
        db.session.add(task)
        db.session.flush()
        EventService.record(
            job,
            "API_TASK_SUBMITTED",
            message=f"API task submitted: {branch_key}",
            node_key=node_run.node_key,
            payload={"api_task_id": task.api_task_id, "model_id": model.model_id},
        )
        return task

    def _complete_task_with_file(
        self,
        job: Job,
        node_run: JobNodeRun,
        task: ApiTask,
        response: dict,
        content: bytes,
        artifact_type: str,
        prompt_version: str | None = None,
        metadata: dict | None = None,
    ) -> Artifact:
        target = StorageService.resolve(task.expected_artifact_path)
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes(content)
        task.status = "success"
        task.response_payload = response
        task.completed_at = utc_now()
        EventService.record(
            job,
            "API_TASK_COMPLETED",
            message=f"API task completed: {task.branch_key}",
            node_key=node_run.node_key,
            payload={"api_task_id": task.api_task_id},
        )
        return ArtifactService.register_artifact(
            job,
            task.expected_artifact_path,
            artifact_type,
            branch_key=task.branch_key,
            node_run=node_run,
            api_task=task,
            model_id=task.model_id,
            prompt_version=prompt_version,
            metadata=metadata,
        )

    def _latest_task(self, job: Job, branch_key: str) -> ApiTask:
        query = ApiTask.query.filter_by(job_id=job.id, branch_key=branch_key)
        current_run_id = JobRunStateService.current_run_id(job)
        task = None
        if current_run_id:
            task = (
                query.filter(ApiTask.request_payload["_run_id"].as_string() == current_run_id)
                .order_by(ApiTask.created_at.desc())
                .first()
            )
        else:
            task = query.order_by(ApiTask.created_at.desc()).first()
        if not task:
            raise AppError(
                "DEPENDENCY_MISSING",
                f"No API task found for branch {branch_key}",
                400,
            )
        return task

    def _prompt(self, job: Job, prompt_type: str, required: bool = True):
        def usable(candidate):
            if not candidate:
                return None
            if (
                PromptSyncService.is_business_prompt(candidate.prompt_type)
                and not PromptSyncService.is_usable_business_prompt(candidate)
            ):
                return None
            return candidate

        if JobRunStateService.prompt_policy(job) == "template_first":
            prompt = usable(PromptService.get_active_for_template(job.template, prompt_type))
            if not prompt:
                prompt = usable(
                    PromptService.get_active_for_template(
                        job.template, prompt_type, job_id=job.id
                    )
                )
        else:
            prompt = usable(
                PromptService.get_active_for_template(
                    job.template, prompt_type, job_id=job.id
                )
            )
            if not prompt:
                prompt = usable(
                    PromptService.get_active_for_template(job.template, prompt_type)
                )
        if required and not prompt:
            raise AppError(
                "PROMPT_NOT_FOUND",
                f"Active prompt not found: {prompt_type}",
                404,
            )
        if prompt:
            PromptService.snapshot_for_job(job, prompt)
        return prompt

    def _get_user_edited_prompt(self, job: Job, prompt_type: str) -> PromptVersion | None:
        active = PromptService.get_active_for_template(
            job.template, prompt_type, job_id=job.id
        )
        if active and active.source in self.USER_EDIT_SOURCES:
            return active
        return None

    def _run_reverse_prompts(self, job: Job, node, node_run: JobNodeRun) -> dict:
        prompt = self._prompt(job, "video_understanding_system", required=False)
        model = self._model_for(job, node, "video_understanding", "DEFAULT_VIDEO_UNDERSTANDING_MODEL")
        adapter, payload, response = self._adapter_payload(
            model,
            {
                "task": "reverse_video_prompts",
                "source_video_path": job.source_video_path,
                "system_prompt": "",
                "user_prompt": prompt.content if prompt else "",
                "expect_json": False,
            },
            job=job,
            node=node,
            param_key="video_understanding",
        )
        t2v_content = self._text_prompt_response(response, "t2v")
        result = {
            "model_response": response,
            "media_inputs": {"source_video_path": job.source_video_path},
            "request_metadata": {
                "model_id": model.model_id,
                "prompt_type": "t2v",
                "output_format": "markdown",
                "expect_json": False,
            },
        }
        raw_path = self._write_json_artifact(
            job,
            node_run,
            ["raw", "reverse_prompts.json"],
            result,
            "raw_response",
            "reverse_prompts",
            model_id=model.model_id,
        )
        created = []
        prompt_objects = []
        for prompt_type in ("t2v",):
            user_edit = self._get_user_edited_prompt(job, prompt_type)
            if user_edit:
                PromptService.snapshot_for_job(job, user_edit)
                EventService.record(
                    job,
                    "PROMPT_USER_EDIT_PRESERVED",
                    message=f"User-edited prompt preserved: {prompt_type} {user_edit.version}",
                    node_key=node_run.node_key,
                    payload={"prompt_type": prompt_type, "version": user_edit.version,
                             "source": user_edit.source},
                )
                created.append(user_edit.to_dict())
                prompt_objects.append(user_edit)
                continue
            prompt = PromptService.create_version_for_template(
                job.template,
                {
                    "prompt_type": prompt_type,
                    "job_id": job.job_id,
                    "title": f"{prompt_type} generated by reverse_prompts",
                    "content": t2v_content,
                    "content_format": "markdown",
                    "source": "reverse_prompts",
                    "activate": True,
                },
            )
            db.session.flush()
            PromptService.snapshot_for_job(job, prompt)
            PromptSyncService.sync_job_prompt_to_template(prompt, reason="reverse_prompts")
            EventService.record(
                job,
                "PROMPT_VERSION_CREATED",
                message=f"Prompt version created: {prompt_type} {prompt.version}",
                node_key=node_run.node_key,
                payload={"prompt_type": prompt_type, "version": prompt.version},
            )
            created.append(prompt.to_dict())
            prompt_objects.append(prompt)
        prompt_files = self._write_prompt_files_for_created(
            job, node_run, prompt_objects, "reverse_prompts"
        )
        return {
            "raw_artifact_path": raw_path,
            "created_prompts": created,
            "payload": payload,
            **prompt_files,
        }

    def _run_submit_t2v(self, job: Job, node, node_run: JobNodeRun) -> dict:
        prompt = self._prompt(job, "t2v")
        model = self._model_for(job, node, "t2v", "DEFAULT_T2V_MODEL")
        adapter, payload, response = self._adapter_payload(
            model,
            {"prompt": prompt.content, "prompt_version": prompt.version,
             "negative_prompt": self._negative_prompt(job)},
            job=job,
            node=node,
            param_key="t2v",
        )
        base = ["outputs", "t2v", prompt.version]
        self._write_json_artifact(
            job, node_run, base + ["request_payload.json"], payload, "request_payload", "t2v", model.model_id, prompt.version
        )
        self._write_json_artifact(
            job, node_run, base + ["response.json"], response, "api_response", "t2v", model.model_id, prompt.version
        )
        expected_path = f"jobs/{job.job_id}/outputs/t2v/{prompt.version}/video.mp4"
        task = self._create_api_task(job, node_run, "t2v", model, payload, response, expected_path)
        return {
            "api_task_id": task.api_task_id,
            "provider_task_id": task.provider_task_id,
            "expected_artifact_path": expected_path,
            "adapter": adapter.__class__.__name__,
        }

    def _run_poll_t2v(self, job: Job, node, node_run: JobNodeRun) -> dict:
        task = self._latest_task(job, "t2v")
        model = self._get_model(task.model_id)
        adapter = get_adapter(task.adapter_name, model=model)
        response = self._poll_until_complete(adapter, task)
        artifact = self._complete_task_from_adapter(
            job,
            node_run,
            task,
            adapter,
            response,
            "t2v_video",
            prompt_version=self._prompt(job, "t2v").version,
        )
        return {"api_task_id": task.api_task_id, "artifact": artifact.to_dict()}

    def _run_submit_first_frame_image(self, job: Job, node, node_run: JobNodeRun) -> dict:
        prompt = self._prompt(job, "first_frame_image")
        model = self._model_for(job, node, "image", "DEFAULT_IMAGE_MODEL")
        adapter, effective_adapter_name, payload, response = self._i2i_test_image_adapter_payload(
            model,
            {"prompt": prompt.content, "prompt_version": prompt.version},
            job=job,
            node=node,
            param_key="image",
        )
        base = ["outputs", "first_frame_image", prompt.version]
        self._write_json_artifact(
            job,
            node_run,
            base + ["request_payload.json"],
            payload,
            "request_payload",
            "first_frame_image",
            model.model_id,
            prompt.version,
        )
        self._write_json_artifact(
            job,
            node_run,
            base + ["response.json"],
            response,
            "api_response",
            "first_frame_image",
            model.model_id,
            prompt.version,
        )
        expected_path = (
            f"jobs/{job.job_id}/outputs/first_frame_image/{prompt.version}/first_frame.png"
        )
        task = self._create_api_task(
            job,
            node_run,
            "first_frame_image",
            model,
            payload,
            response,
            expected_path,
            adapter_name=effective_adapter_name,
        )
        return {
            "api_task_id": task.api_task_id,
            "provider_task_id": task.provider_task_id,
            "expected_artifact_path": expected_path,
            "adapter": adapter.__class__.__name__,
        }

    def _run_poll_first_frame_image(self, job: Job, node, node_run: JobNodeRun) -> dict:
        task = self._latest_task(job, "first_frame_image")
        model = self._get_model(task.model_id)
        adapter = get_adapter(task.adapter_name, model=model)
        response = self._poll_until_complete(adapter, task)
        artifact = self._complete_task_from_adapter(
            job,
            node_run,
            task,
            adapter,
            response,
            "first_frame_image",
            prompt_version=self._prompt(job, "first_frame_image").version,
        )
        return {"api_task_id": task.api_task_id, "artifact": artifact.to_dict()}

    def _run_rewrite_prompts(self, job: Job, node, node_run: JobNodeRun) -> dict:
        t2v = self._prompt(job, "t2v")
        prompt = self._prompt(job, "prompt_rewrite_system", required=False)
        model = self._model_for(job, node, "prompt_rewrite", "DEFAULT_PROMPT_REWRITE_MODEL")
        rendered_user_prompt = self._render_prompt_template(
            prompt.content if prompt else "",
            t2v_prompts=t2v.content,
            t2v_prompt=t2v.content,
        )
        adapter, payload, response = self._adapter_payload(
            model,
            {
                "task": "rewrite_video_prompts",
                "t2v_prompt": t2v.content,
                "system_prompt": "",
                "user_prompt": rendered_user_prompt,
                "schema_name": "rewrite_video_prompts",
                "response_schema": self._schema_for(["first_frame_image", "i2v"]),
            },
            job=job,
            node=node,
            param_key="prompt_rewrite",
        )
        data = self._strict_json_response(response, ["first_frame_image", "i2v"])
        rewritten = {
            "first_frame_image": data["first_frame_image"],
            "i2v": data["i2v"],
            "model_response": response,
        }
        raw_path = self._write_json_artifact(
            job,
            node_run,
            ["raw", "rewrite_prompts.json"],
            rewritten,
            "raw_response",
            "rewrite_prompts",
            model_id=model.model_id,
        )
        created = []
        prompt_objects = []
        for prompt_type in ("first_frame_image", "i2v"):
            user_edit = self._get_user_edited_prompt(job, prompt_type)
            if user_edit:
                PromptService.snapshot_for_job(job, user_edit)
                EventService.record(
                    job,
                    "PROMPT_USER_EDIT_PRESERVED",
                    message=f"User-edited prompt preserved: {prompt_type} {user_edit.version}",
                    node_key=node_run.node_key,
                    payload={"prompt_type": prompt_type, "version": user_edit.version,
                             "source": user_edit.source},
                )
                created.append(user_edit.to_dict())
                prompt_objects.append(user_edit)
                continue
            prompt = PromptService.create_version_for_template(
                job.template,
                {
                    "prompt_type": prompt_type,
                    "job_id": job.job_id,
                    "title": f"{prompt_type} generated by rewrite_prompts",
                    "content": rewritten[prompt_type],
                    "content_format": "markdown",
                    "source": "rewrite_prompts",
                    "parent_version": t2v.version,
                    "activate": True,
                },
            )
            db.session.flush()
            PromptService.snapshot_for_job(job, prompt)
            PromptSyncService.sync_job_prompt_to_template(prompt, reason="rewrite_prompts")
            EventService.record(
                job,
                "PROMPT_VERSION_CREATED",
                message=f"Prompt version created: {prompt_type} {prompt.version}",
                node_key=node_run.node_key,
                payload={"prompt_type": prompt_type, "version": prompt.version},
            )
            created.append(prompt.to_dict())
            prompt_objects.append(prompt)
        prompt_files = self._write_prompt_files_for_created(
            job, node_run, prompt_objects, "rewrite_prompts"
        )
        return {
            "raw_artifact_path": raw_path,
            "created_prompts": created,
            "payload": payload,
            **prompt_files,
        }

    def _run_reverse_prompts4r2v(self, job: Job, node, node_run: JobNodeRun) -> dict:
        t2v = self._prompt(job, "t2v")
        prompt = self._prompt(job, "reverse_prompts4r2v_system", required=False)
        model = self._model_for(job, node, "prompt_rewrite", "DEFAULT_PROMPT_REWRITE_MODEL")
        rendered_user_prompt = self._render_prompt_template(
            prompt.content if prompt else "",
            t2v_prompts=t2v.content,
            t2v_prompt=t2v.content,
        )
        adapter, payload, response = self._adapter_payload(
            model,
            {
                "task": "reverse_prompts4r2v",
                "t2v_prompt": t2v.content,
                "system_prompt": "",
                "user_prompt": rendered_user_prompt,
                "schema_name": "reverse_prompts4r2v",
                "response_schema": self._schema_for(["r2v_flash"]),
            },
            job=job,
            node=node,
            param_key="prompt_rewrite",
        )
        data = self._strict_json_response(response, ["r2v_flash"])
        rewritten = {
            "r2v_flash": data["r2v_flash"],
            "model_response": response,
        }
        raw_path = self._write_json_artifact(
            job,
            node_run,
            ["raw", "reverse_prompts4r2v.json"],
            rewritten,
            "raw_response",
            "reverse_prompts4r2v",
            model_id=model.model_id,
        )
        user_edit = self._get_user_edited_prompt(job, "r2v_flash")
        if user_edit:
            PromptService.snapshot_for_job(job, user_edit)
            EventService.record(
                job,
                "PROMPT_USER_EDIT_PRESERVED",
                message=f"User-edited prompt preserved: r2v_flash {user_edit.version}",
                node_key=node_run.node_key,
                payload={"prompt_type": "r2v_flash", "version": user_edit.version,
                         "source": user_edit.source},
            )
            prompt = user_edit
        else:
            prompt = PromptService.create_version_for_template(
                job.template,
                {
                    "prompt_type": "r2v_flash",
                    "job_id": job.job_id,
                    "title": "r2v_flash generated by reverse_prompts4r2v",
                    "content": rewritten["r2v_flash"],
                    "content_format": "markdown",
                    "source": "reverse_prompts4r2v",
                    "parent_version": t2v.version,
                    "activate": True,
                },
            )
            db.session.flush()
            PromptService.snapshot_for_job(job, prompt)
            PromptSyncService.sync_job_prompt_to_template(prompt, reason="reverse_prompts4r2v")
            EventService.record(
                job,
                "PROMPT_VERSION_CREATED",
                message=f"Prompt version created: r2v_flash {prompt.version}",
                node_key=node_run.node_key,
                payload={"prompt_type": "r2v_flash", "version": prompt.version},
            )
        prompt_files = self._write_prompt_files_for_created(
            job, node_run, [prompt], "reverse_prompts4r2v"
        )
        return {
            "raw_artifact_path": raw_path,
            "created_prompts": [prompt.to_dict()],
            "payload": payload,
            "adapter": adapter.__class__.__name__,
            **prompt_files,
        }

    def _run_submit_r2v_flash(self, job: Job, node, node_run: JobNodeRun) -> dict:
        prompt = self._prompt(job, "r2v_flash")
        references = (
            Artifact.query.filter_by(job_id=job.id, artifact_type="reference_image")
            .order_by(Artifact.created_at.asc())
            .all()
        )
        reference_source = "uploaded_or_existing"
        if not references:
            references = self._sample_local_r2v_references(job, node, node_run)
            reference_source = "local_random"
        if not references:
            search_dirs = ", ".join(self._r2v_reference_image_dirs(job, node))
            raise AppError(
                "DEPENDENCY_MISSING",
                (
                    "No R2V reference image available. Upload reference_images "
                    f"or add image files under: {search_dirs}"
                ),
                400,
            )

        model = self._model_for(job, node, "r2v_flash", "DEFAULT_R2V_FLASH_MODEL")
        adapter, payload, response = self._adapter_payload(
            model,
            {
                "prompt": prompt.content,
                "prompt_version": prompt.version,
                "reference_images": [item.file_path for item in references],
                "negative_prompt": self._negative_prompt(job),
            },
            job=job,
            node=node,
            param_key="r2v_flash",
        )
        base = ["outputs", "r2v_flash", prompt.version]
        self._write_json_artifact(
            job, node_run, base + ["request_payload.json"], payload, "request_payload", "r2v_flash", model.model_id, prompt.version
        )
        self._write_json_artifact(
            job, node_run, base + ["response.json"], response, "api_response", "r2v_flash", model.model_id, prompt.version
        )
        expected_path = f"jobs/{job.job_id}/outputs/r2v_flash/{prompt.version}/video_1.mp4"
        task = self._create_api_task(
            job, node_run, "r2v_flash", model, payload, response, expected_path
        )
        return {
            "api_task_ids": [task.api_task_id],
            "expected_artifact_paths": [expected_path],
            "reference_source": reference_source,
            "reference_image_artifact_ids": [item.artifact_id for item in references],
            "adapter": adapter.__class__.__name__,
        }

    def _sample_local_r2v_references(self, job: Job, node, node_run: JobNodeRun) -> list[Artifact]:
        image_pool = []
        seen = set()
        for directory in self._r2v_reference_image_dirs(job, node):
            for image_path in I2ITestBatchService._image_pool(directory):
                marker = str(image_path)
                if marker in seen:
                    continue
                seen.add(marker)
                image_pool.append(image_path)
        if not image_pool:
            return []

        sample_count = self._r2v_reference_sample_count(job, node)
        selected = random.SystemRandom().sample(
            image_pool,
            k=min(sample_count, len(image_pool)),
        )
        artifacts = []
        for index, source_path in enumerate(selected, start=1):
            suffix = source_path.suffix.lower() or ".bin"
            target_path = StorageService.copy_into_job(
                job.job_id,
                source_path,
                ["raw", "r2v_reference_images", f"reference_{index:03d}{suffix}"],
            )
            artifact = ArtifactService.register_artifact(
                job,
                target_path,
                "reference_image",
                branch_key="r2v_flash",
                node_run=node_run,
                metadata={
                    "source": "local_random",
                    "source_dataset_path": str(source_path),
                },
            )
            artifacts.append(artifact)
        return artifacts

    def _r2v_reference_sample_count(self, job: Job, node) -> int:
        node_config = self._node_config(job, node)
        job_config = job.config or {}
        node_ref = dict(node_config.get("r2v_reference") or {})
        job_ref = dict(job_config.get("r2v_reference") or {})
        raw_value = (
            job_ref.get("sample_count")
            or node_ref.get("sample_count")
            or node_config.get("reference_sample_count")
            or 1
        )
        try:
            sample_count = int(raw_value)
        except (TypeError, ValueError):
            sample_count = 1
        return max(1, min(sample_count, 20))

    def _r2v_reference_image_dirs(self, job: Job, node) -> list[str]:
        node_config = self._node_config(job, node)
        job_config = job.config or {}
        node_ref = dict(node_config.get("r2v_reference") or {})
        job_ref = dict(job_config.get("r2v_reference") or {})
        configured = (
            job_ref.get("image_dirs")
            or job_ref.get("reference_image_dirs")
            or job_config.get("r2v_reference_image_dirs")
            or node_ref.get("image_dirs")
            or node_ref.get("reference_image_dirs")
            or node_config.get("reference_image_dirs")
            or current_app.config.get("R2V_REFERENCE_IMAGE_DIRS")
        )
        paths = NodeRunner._split_config_paths(configured)
        if paths:
            return paths
        return [
            current_app.config["I2I_TEST_MALE_DATASET_DIR"],
            current_app.config["I2I_TEST_FEMALE_DATASET_DIR"],
        ]

    @staticmethod
    def _split_config_paths(value) -> list[str]:
        if isinstance(value, (list, tuple)):
            return [str(item).strip() for item in value if str(item).strip()]
        if isinstance(value, str):
            return [
                item.strip()
                for chunk in value.split(";")
                for item in chunk.split(",")
                if item.strip()
            ]
        return []

    def _run_poll_r2v_flash(self, job: Job, node, node_run: JobNodeRun) -> dict:
        tasks = (
            ApiTask.query.filter_by(job_id=job.id, branch_key="r2v_flash")
            .order_by(ApiTask.created_at.asc())
            .all()
        )
        if not tasks:
            raise AppError("DEPENDENCY_MISSING", "No R2V API tasks found", 400)
        artifacts = []
        prompt = self._prompt(job, "r2v_flash")
        for task in tasks:
            model = self._get_model(task.model_id)
            adapter = get_adapter(task.adapter_name, model=model)
            response = self._poll_until_complete(adapter, task)
            artifact = self._complete_task_from_adapter(
                job,
                node_run,
                task,
                adapter,
                response,
                "r2v_flash_video",
                prompt_version=prompt.version,
            )
            artifacts.append(artifact.to_dict())
        return {"artifacts": artifacts}

    def _run_submit_i2v(self, job: Job, node, node_run: JobNodeRun) -> dict:
        prompt = self._prompt(job, "i2v")
        first_frame = ArtifactService.latest_for_job(job, "first_frame_image")
        if not first_frame:
            raise AppError(
                "DEPENDENCY_MISSING",
                "first_frame_image artifact is required before submit_i2v",
                400,
            )
        model = self._model_for_any(job, node, ["main_i2v", "i2v"], "DEFAULT_I2V_MODEL")
        adapter, payload, response = self._adapter_payload(
            model,
            {
                "prompt": prompt.content,
                "prompt_version": prompt.version,
                "first_frame_image": first_frame.file_path,
                "negative_prompt": self._negative_prompt(job),
            },
            job=job,
            node=node,
            param_key="i2v",
        )
        base = ["outputs", "i2v", f"{prompt.version}_img_{first_frame.artifact_id}"]
        self._write_json_artifact(
            job, node_run, base + ["request_payload.json"], payload, "request_payload", "i2v", model.model_id, prompt.version
        )
        self._write_json_artifact(
            job, node_run, base + ["response.json"], response, "api_response", "i2v", model.model_id, prompt.version
        )
        expected_path = (
            f"jobs/{job.job_id}/outputs/i2v/{prompt.version}_img_{first_frame.artifact_id}/video.mp4"
        )
        task = self._create_api_task(job, node_run, "i2v", model, payload, response, expected_path)
        return {
            "api_task_id": task.api_task_id,
            "provider_task_id": task.provider_task_id,
            "expected_artifact_path": expected_path,
            "adapter": adapter.__class__.__name__,
        }

    def _run_poll_i2v(self, job: Job, node, node_run: JobNodeRun) -> dict:
        task = self._latest_task(job, "i2v")
        model = self._get_model(task.model_id)
        adapter = get_adapter(task.adapter_name, model=model)
        response = self._poll_until_complete(adapter, task)
        artifact = self._complete_task_from_adapter(
            job,
            node_run,
            task,
            adapter,
            response,
            "i2v_video",
            prompt_version=self._prompt(job, "i2v").version,
        )
        return {"api_task_id": task.api_task_id, "artifact": artifact.to_dict()}

    def _run_prepare_i2i_test_batch(self, job: Job, node, node_run: JobNodeRun) -> dict:
        prompt = self._prompt(job, "i2i")
        batch = I2ITestBatchService.prepare_batch(
            job, node_run, node_config=self._node_config(job, node)
        )
        return {
            "prompt_version": prompt.version,
            "mode": batch["mode"],
            "test_count": batch["test_count"],
            "image_model": batch["image_model"],
            "i2v_model": batch["i2v_model"],
            "items": batch["items"],
        }

    def _run_submit_i2i_test_image(self, job: Job, node, node_run: JobNodeRun) -> dict:
        i2i_prompt = self._prompt(job, "i2i")
        batch = (job.config or {}).get("i2i_test_batch") or {}
        items = batch.get("items") or []
        if not items:
            raise AppError(
                "DEPENDENCY_MISSING",
                "i2i_test_batch is required before submit_i2i_test_image",
                400,
            )

        job_config = job.config or {}
        node_key = node.node_key if node else None
        node_model = self._node_config(job, node).get("model_id") if node else None
        node_override = (job_config.get("node_models") or {}).get(node_key)
        job_i2i = dict(job_config.get("i2i_test") or {})
        model_id = (
            node_override
            or job_i2i.get("image_model")
            or ((job_config.get("models") or {}).get("i2i_test_image"))
            or node_model
            or batch.get("image_model")
            or current_app.config["DEFAULT_I2I_TEST_IMAGE_MODEL"]
        )
        model = self._get_model(model_id)
        task_results = []
        skipped_failed = 0

        for item in items:
            test_index = int(item.get("test_index") or (len(task_results) + skipped_failed + 1))
            source_image = item.get("primary_image")
            if not source_image:
                item["image_status"] = "failed"
                item["image_error"] = f"missing source image for test #{test_index}"
                skipped_failed += 1
                continue

            item_mode = item.get("mode") or batch.get("mode")
            try:
                # wan2.7-image is a multimodal model: it must use the multimodal-generation
                # endpoint (synchronous) instead of the image-generation endpoint (async).
                # Using the wrong endpoint with enable_interleave=True causes random
                # "输入/输出不合适" errors when person reference images are supplied.
                adapter, effective_adapter_name, payload, response = (
                    self._i2i_test_image_adapter_payload(
                        model,
                        {
                            "prompt": i2i_prompt.content,
                            "prompt_version": i2i_prompt.version,
                            "source_image": source_image,
                            "test_index": test_index,
                            "mode": item_mode,
                            "source_images": item.get("source_images") or [],
                            "branch_key": "i2i_test",
                        },
                        job=job,
                        node=node,
                        param_key="i2i_test_image",
                    )
                )
                request_payload = {
                    **payload,
                    "test_index": test_index,
                    "mode": item_mode,
                    "source_image": source_image,
                    "source_images": item.get("source_images") or [],
                    "primary_role": item.get("primary_role"),
                    "i2i_prompt_version": i2i_prompt.version,
                }
                base = ["outputs", "i2i_test_image", f"test_{test_index:03d}"]
                self._write_json_artifact(
                    job, node_run, base + ["request_payload.json"],
                    request_payload, "request_payload", "i2i_test", model.model_id, i2i_prompt.version,
                )
                self._write_json_artifact(
                    job, node_run, base + ["response.json"],
                    response, "api_response", "i2i_test", model.model_id, i2i_prompt.version,
                )
                expected_path = (
                    f"jobs/{job.job_id}/outputs/i2i_test_image/test_{test_index:03d}/first_frame.png"
                )
                task = self._create_api_task(
                    job, node_run, "i2i_test_image", model,
                    request_payload, response, expected_path,
                    adapter_name=effective_adapter_name,
                )
                item["image_status"] = "submitted"
                task_results.append(
                    {
                        "test_index": test_index,
                        "api_task_id": task.api_task_id,
                        "provider_task_id": task.provider_task_id,
                        "expected_artifact_path": expected_path,
                        "model_id": model.model_id,
                        "adapter": adapter.__class__.__name__,
                    }
                )
            except AppError as err:
                item["image_status"] = "failed"
                item["image_error"] = err.message
                skipped_failed += 1
                EventService.record(
                    job,
                    "I2I_TEST_IMAGE_SUBMIT_FAILED",
                    message=f"I2I test #{test_index} submit failed: {err.message}",
                    node_key=node_run.node_key,
                    level="warning",
                )
                try:
                    StorageService.append_job_log(job.job_id, "i2i_sample", {
                        "test_index": test_index,
                        "stage": "submit_image",
                        "status": "failed",
                        "error": err.message,
                    })
                except Exception:
                    pass

        # Persist per-sample status back to job config
        batch["items"] = items
        job.config = {**(job.config or {}), "i2i_test_batch": batch}
        db.session.flush()

        if not task_results:
            sample_errors = [
                f"#{i.get('test_index')}: {i.get('image_error', 'unknown')}"
                for i in items if i.get("image_status") == "failed"
            ]
            raise AppError(
                "API_TASK_FAILED",
                "All I2I test image submissions failed — "
                + ("; ".join(sample_errors) if sample_errors else "no detail"),
                502,
            )

        return {
            "tasks": task_results,
            "skipped_failed": skipped_failed,
            "i2i_prompt_version": i2i_prompt.version,
        }

    def _run_poll_i2i_test_image(self, job: Job, node, node_run: JobNodeRun) -> dict:
        """Poll all I2I test image tasks.

        Fault-tolerant: a single sample failure does not abort the node.
        Pipeline: for each successful first-frame, immediately submit the i2v task so
        video generation starts without waiting for all images to complete.
        The node only fails when ALL samples fail.
        """
        tasks = (
            ApiTask.query.filter_by(job_id=job.id, branch_key="i2i_test_image")
            .order_by(ApiTask.created_at.asc())
            .all()
        )
        if not tasks:
            raise AppError("DEPENDENCY_MISSING", "No I2I test image API tasks found", 400)

        prompt = self._prompt(job, "i2i")
        i2v_prompt = self._prompt(job, "i2v")
        i2i_prompt = self._prompt(job, "i2i", required=False)
        i2v_model = self._resolve_i2i_i2v_model(job, node)

        batch = dict((job.config or {}).get("i2i_test_batch") or {})
        items = list(batch.get("items") or [])
        by_index = {
            int(item.get("test_index") or idx + 1): dict(item)
            for idx, item in enumerate(items)
        }

        success_artifacts = []
        failure_count = 0

        for task in tasks:
            model = self._get_model(task.model_id)
            adapter = get_adapter(task.adapter_name, model=model)
            request_payload = task.request_payload or {}
            test_index = int(request_payload.get("test_index") or 0)
            item = by_index.get(test_index, {"test_index": test_index})

            try:
                response = self._poll_until_complete(adapter, task)
                artifact = self._complete_task_from_adapter(
                    job,
                    node_run,
                    task,
                    adapter,
                    response,
                    "i2i_test_first_frame_image",
                    prompt_version=prompt.version,
                    metadata={
                        "test_index": test_index,
                        "mode": request_payload.get("mode"),
                        "source_image": request_payload.get("source_image"),
                        "source_images": request_payload.get("source_images") or [],
                        "primary_role": request_payload.get("primary_role"),
                    },
                    artifact_branch_key="i2i_test",
                )
                item["generated_first_frame_image"] = artifact.file_path
                item["generated_first_frame_artifact_id"] = artifact.artifact_id
                item["image_status"] = "success"
                success_artifacts.append(artifact.to_dict())

                # ── Inline pipeline: immediately submit i2v for this sample ──
                try:
                    i2v_task = self._submit_i2i_i2v_task_for_sample(
                        job, node_run, artifact, item, i2v_model, i2v_prompt, i2i_prompt, node,
                    )
                    item["i2v_api_task_id"] = i2v_task.api_task_id
                    EventService.record(
                        job,
                        "I2I_TEST_I2V_SUBMITTED",
                        message=f"I2I test #{test_index}: i2v submitted inline",
                        node_key=node_run.node_key,
                        payload={"test_index": test_index, "api_task_id": i2v_task.api_task_id},
                    )
                except Exception as exc_i2v:
                    item["i2v_api_task_id"] = None
                    EventService.record(
                        job,
                        "I2I_TEST_I2V_SUBMIT_FAILED",
                        message=f"I2I test #{test_index}: inline i2v submit failed — {exc_i2v}",
                        node_key=node_run.node_key,
                        level="warning",
                    )

            except AppError as err:
                failure_count += 1
                item["image_status"] = "failed"
                item["image_error"] = err.message
                EventService.record(
                    job,
                    "I2I_TEST_IMAGE_FAILED",
                    message=f"I2I test #{test_index}: image failed — {err.message}",
                    node_key=node_run.node_key,
                    level="warning",
                )

            if test_index:
                by_index[test_index] = item

            # Persist sample outcome to log file
            try:
                StorageService.append_job_log(job.job_id, "i2i_sample", {
                    "test_index": test_index,
                    "stage": "poll_image",
                    "status": item.get("image_status"),
                    "error": item.get("image_error"),
                    "artifact_id": item.get("generated_first_frame_artifact_id"),
                })
            except Exception:
                pass

        batch["items"] = [by_index[k] for k in sorted(by_index)]
        job.config = {**(job.config or {}), "i2i_test_batch": batch}
        db.session.flush()

        if not success_artifacts:
            sample_errors = [
                f"#{ti}: {itm.get('image_error', 'unknown')}"
                for ti, itm in sorted(by_index.items())
                if itm.get("image_status") == "failed"
            ]
            raise AppError(
                "API_TASK_FAILED",
                f"All {len(tasks)} I2I test image task(s) failed — "
                + ("; ".join(sample_errors) if sample_errors else "no detail"),
                502,
            )

        return {"artifacts": success_artifacts, "failed_count": failure_count}

    def _resolve_i2i_i2v_model(self, job: Job, node) -> ModelRegistry:
        """Select the i2v model for I2I test, used by both poll_image (pipeline) and submit_i2v."""
        job_config = job.config or {}
        batch = job_config.get("i2i_test_batch") or {}
        node_key = node.node_key if node else None
        node_model = self._node_config(job, node).get("model_id") if node else None
        node_override = (job_config.get("node_models") or {}).get(node_key)
        job_i2i = dict(job_config.get("i2i_test") or {})
        model_id = (
            node_override
            or job_i2i.get("i2v_model")
            or ((job_config.get("models") or {}).get("i2i_test_i2v"))
            or node_model
            or batch.get("i2v_model")
            or current_app.config["DEFAULT_I2I_TEST_I2V_MODEL"]
        )
        return self._get_model(model_id)

    def _submit_i2i_i2v_task_for_sample(
        self,
        job: Job,
        node_run: JobNodeRun,
        first_frame: Artifact,
        item: dict,
        model: ModelRegistry,
        i2v_prompt,
        i2i_prompt,
        node,
    ) -> ApiTask:
        """Submit a single sample's i2i_test_i2v task.  Called from poll_image (pipeline) and
        submit_i2v (catch-up).  Returns the created ApiTask."""
        test_index = int(item.get("test_index") or 0)
        item_mode = item.get("mode")
        shot_type = I2ITestBatchService.shot_type_for_mode(item_mode)
        adapter, payload, response = self._adapter_payload(
            model,
            {
                "prompt": i2v_prompt.content,
                "prompt_version": i2v_prompt.version,
                "first_frame_image": first_frame.file_path,
                "test_index": test_index,
                "mode": item_mode,
                "source_images": item.get("source_images") or [],
                "i2i_first_frame_artifact_id": first_frame.artifact_id,
                "branch_key": "i2i_test",
                "negative_prompt": self._negative_prompt(job),
            },
            params={"shot_type": shot_type},
            job=job,
            node=node,
            param_key="i2i_test_i2v",
        )
        request_payload = {
            **payload,
            "test_index": test_index,
            "mode": item_mode,
            "shot_type": shot_type,
            "source_images": item.get("source_images") or [],
            "primary_role": item.get("primary_role"),
            "source_image": item.get("primary_image"),
            "i2i_first_frame_image": first_frame.file_path,
            "i2i_first_frame_artifact_id": first_frame.artifact_id,
            "i2i_prompt": i2i_prompt.content if i2i_prompt else None,
            "i2i_prompt_version": i2i_prompt.version if i2i_prompt else None,
            "i2v_prompt_version": i2v_prompt.version,
        }
        base = ["outputs", "i2i_test_i2v", f"test_{test_index:03d}"]
        self._write_json_artifact(
            job, node_run, base + ["request_payload.json"],
            request_payload, "request_payload", "i2i_test", model.model_id, i2v_prompt.version,
        )
        self._write_json_artifact(
            job, node_run, base + ["response.json"],
            response, "api_response", "i2i_test", model.model_id, i2v_prompt.version,
        )
        expected_path = f"jobs/{job.job_id}/outputs/i2i_test_i2v/test_{test_index:03d}/video.mp4"
        return self._create_api_task(
            job, node_run, "i2i_test_i2v", model, request_payload, response, expected_path,
        )

    def _run_submit_i2i_test_i2v(self, job: Job, node, node_run: JobNodeRun) -> dict:
        """Catch-up node: submit i2v for any samples not yet submitted by the inline pipeline."""
        i2v_prompt = self._prompt(job, "i2v")
        i2i_prompt = self._prompt(job, "i2i", required=False)
        batch = dict((job.config or {}).get("i2i_test_batch") or {})
        items = list(batch.get("items") or [])
        if not items:
            raise AppError(
                "DEPENDENCY_MISSING",
                "i2i_test_batch is required before submit_i2i_test_i2v",
                400,
            )

        first_frames = (
            Artifact.query.filter_by(
                job_id=job.id,
                artifact_type="i2i_test_first_frame_image",
                branch_key="i2i_test",
            )
            .order_by(Artifact.created_at.asc())
            .all()
        )
        first_frame_by_index = {}
        for artifact in first_frames:
            meta = artifact.meta or {}
            try:
                first_frame_by_index[int(meta.get("test_index"))] = artifact
            except (TypeError, ValueError):
                continue

        model = self._resolve_i2i_i2v_model(job, node)
        task_results = []
        skipped_failed = 0
        skipped_pipeline = 0

        for item in items:
            test_index = int(item.get("test_index") or (len(task_results) + skipped_failed + skipped_pipeline + 1))

            # Skip samples whose image failed
            if item.get("image_status") == "failed":
                skipped_failed += 1
                continue

            # Skip samples already submitted by the inline pipeline in poll_image
            if item.get("i2v_api_task_id"):
                skipped_pipeline += 1
                continue

            first_frame = first_frame_by_index.get(test_index)
            if not first_frame and item.get("generated_first_frame_artifact_id"):
                first_frame = Artifact.query.filter_by(
                    artifact_id=item["generated_first_frame_artifact_id"]
                ).first()
            if not first_frame:
                item["image_status"] = "failed"
                item["image_error"] = f"first-frame artifact not found for test #{test_index}"
                skipped_failed += 1
                continue

            task = self._submit_i2i_i2v_task_for_sample(
                job, node_run, first_frame, item, model, i2v_prompt, i2i_prompt, node,
            )
            item["i2v_api_task_id"] = task.api_task_id
            task_results.append(
                {
                    "test_index": test_index,
                    "api_task_id": task.api_task_id,
                    "provider_task_id": task.provider_task_id,
                    "model_id": model.model_id,
                }
            )

        batch["items"] = items
        job.config = {**(job.config or {}), "i2i_test_batch": batch}
        db.session.flush()

        if not task_results and skipped_pipeline == 0:
            raise AppError(
                "DEPENDENCY_MISSING",
                "No I2I test i2v tasks could be submitted "
                f"(failed samples: {skipped_failed})",
                400,
            )

        return {
            "tasks": task_results,
            "skipped_failed": skipped_failed,
            "skipped_pipeline": skipped_pipeline,
            "i2i_prompt_version": i2i_prompt.version if i2i_prompt else None,
            "i2v_prompt_version": i2v_prompt.version,
        }

    def _run_poll_i2i_test_i2v(self, job: Job, node, node_run: JobNodeRun) -> dict:
        """Poll all I2I test i2v tasks.

        Fault-tolerant: a single sample failure does not abort the node.
        The node only fails when ALL samples fail.
        """
        tasks = (
            ApiTask.query.filter_by(job_id=job.id, branch_key="i2i_test_i2v")
            .order_by(ApiTask.created_at.asc())
            .all()
        )
        if not tasks:
            raise AppError("DEPENDENCY_MISSING", "No I2I test I2V API tasks found", 400)

        prompt = self._prompt(job, "i2v")
        batch = dict((job.config or {}).get("i2i_test_batch") or {})
        items = list(batch.get("items") or [])
        by_index = {
            int(item.get("test_index") or idx + 1): dict(item)
            for idx, item in enumerate(items)
        }

        success_artifacts = []
        failure_count = 0

        for task in tasks:
            model = self._get_model(task.model_id)
            adapter = get_adapter(task.adapter_name, model=model)
            request_payload = task.request_payload or {}
            test_index = request_payload.get("test_index")
            item = by_index.get(int(test_index or 0), {"test_index": test_index})

            try:
                response = self._poll_until_complete(adapter, task)
                artifact = self._complete_task_from_adapter(
                    job,
                    node_run,
                    task,
                    adapter,
                    response,
                    "i2i_test_video",
                    prompt_version=prompt.version,
                    metadata={
                        "test_index": test_index,
                        "mode": request_payload.get("mode"),
                        "source_images": request_payload.get("source_images") or [],
                        "primary_role": request_payload.get("primary_role"),
                        "source_image": request_payload.get("source_image"),
                        "i2i_first_frame_image": request_payload.get("i2i_first_frame_image"),
                        "i2i_first_frame_artifact_id": request_payload.get("i2i_first_frame_artifact_id"),
                    },
                    artifact_branch_key="i2i_test",
                )
                item["i2v_status"] = "success"
                success_artifacts.append(artifact.to_dict())

            except AppError as err:
                failure_count += 1
                item["i2v_status"] = "failed"
                item["i2v_error"] = err.message
                EventService.record(
                    job,
                    "I2I_TEST_VIDEO_FAILED",
                    message=f"I2I test #{test_index}: video failed — {err.message}",
                    node_key=node_run.node_key,
                    level="warning",
                )

            if test_index is not None:
                try:
                    by_index[int(test_index)] = item
                except (TypeError, ValueError):
                    pass

            # Persist sample outcome to log file
            try:
                StorageService.append_job_log(job.job_id, "i2i_sample", {
                    "test_index": test_index,
                    "stage": "poll_i2v",
                    "status": item.get("i2v_status"),
                    "error": item.get("i2v_error"),
                })
            except Exception:
                pass

        batch["items"] = [by_index[k] for k in sorted(by_index)]
        job.config = {**(job.config or {}), "i2i_test_batch": batch}
        db.session.flush()

        if not success_artifacts:
            sample_errors = [
                f"#{ti}: {itm.get('i2v_error', 'unknown')}"
                for ti, itm in sorted(by_index.items())
                if itm.get("i2v_status") == "failed"
            ]
            raise AppError(
                "API_TASK_FAILED",
                f"All {len(tasks)} I2I test video task(s) failed — "
                + ("; ".join(sample_errors) if sample_errors else "no detail"),
                502,
            )

        return {"artifacts": success_artifacts, "failed_count": failure_count}

    def _run_failure_agent(self, job: Job, node, node_run: JobNodeRun) -> dict:
        from app.models.job_event import JobEvent
        from app.services.error_detail_service import ErrorDetailService

        system_prompt = self._prompt(job, "failure_agent_system", required=False)
        user_prompt = self._prompt(job, "failure_agent_user", required=False)
        latest_failed = (
            JobNodeRun.query.filter(
                JobNodeRun.job_id == job.id,
                JobNodeRun.status.in_(["failed", "path_failed"]),
            )
            .order_by(JobNodeRun.created_at.desc())
            .first()
        )

        # Build full error context so the LLM has enough information to decide
        error_detail = ErrorDetailService.latest_for_job(job)
        recent_error_events = (
            JobEvent.query.filter(
                JobEvent.job_id == job.id,
                JobEvent.level.in_(["error", "warning"]),
            )
            .order_by(JobEvent.created_at.desc())
            .limit(10)
            .all()
        )

        context = {
            "job": job.to_dict(),
            "current_node": job.current_node,
            "latest_failed_run": latest_failed.to_dict() if latest_failed else None,
            # Full error detail including API task response and DashScope error code
            "error_detail": error_detail,
            # Structured node error with output_snapshot (contains error_detail)
            "latest_failed_node_error": (
                {
                    "node_key":      latest_failed.node_key,
                    "error_message": latest_failed.error_message,
                    "error_detail":  (
                        latest_failed.output_snapshot.get("error_detail")
                        if isinstance(latest_failed.output_snapshot, dict) else None
                    ),
                }
                if latest_failed else None
            ),
            # Recent error/warning events for full audit trail
            "recent_error_events": [
                {
                    "event_type": e.event_type,
                    "message":    e.message,
                    "node_key":   e.node_key,
                    "payload":    e.payload,
                }
                for e in recent_error_events
            ],
            "prompt_refs": [ref.to_dict() for ref in job.prompt_refs],
            "api_tasks": [task.to_dict() for task in job.api_tasks[-10:]],
            "budget": {
                "budget_limit": float(job.budget_limit) if job.budget_limit is not None else None,
                "cost_used": float(job.cost_used or 0),
            },
        }
        rendered_user_prompt = self._render_prompt_template(
            user_prompt.content if user_prompt else "{{context_json}}",
            context_json=json.dumps(context, ensure_ascii=False, indent=2),
        )
        schema = {
            "type": "object",
            "properties": {
                "action": {
                    "type": "string",
                    "enum": [
                        "RETRY_NODE",
                        "CONTINUE_FROM_NODE",
                        "SKIP_NODE",
                        "PAUSE_JOB",
                        "CANCEL_JOB",
                        "NEED_HUMAN",
                    ],
                },
                "reason": {"type": "string"},
                "target_node": {"type": ["string", "null"]},
                "sleep_sec": {"type": "number"},
            },
            "required": ["action", "reason", "target_node", "sleep_sec"],
            "additionalProperties": False,
        }
        model = self._model_for(job, node, "failure_agent", "DEFAULT_PROMPT_REWRITE_MODEL")
        adapter, payload, response = self._adapter_payload(
            model,
            {
                "task": "failure_decision",
                "system_prompt": system_prompt.content if system_prompt else "",
                "user_prompt": rendered_user_prompt,
                "schema_name": "failure_decision",
                "response_schema": schema,
            },
            params={"temperature": 0.0},
            job=job,
            node=node,
            param_key="failure_agent",
        )
        data = response.get("json") or {}
        decision = {
            "action": data.get("action") or "NEED_HUMAN",
            "reason": data.get("reason") or "No model decision was available",
            "target_node": data.get("target_node"),
            "sleep_sec": float(data.get("sleep_sec") or 0),
            "model_response": response,
            "adapter": adapter.__class__.__name__,
        }
        raw_path = self._write_json_artifact(
            job,
            node_run,
            ["raw", "failure_agent.json"],
            decision,
            "raw_response",
            "failure_agent",
            model_id=model.model_id,
        )
        EventService.record(
            job,
            "FAILURE_AGENT_DECISION",
            message=f"Failure agent decision: {decision['action']}",
            node_key=node_run.node_key,
            payload={key: decision[key] for key in ("action", "reason", "target_node", "sleep_sec")},
        )
        return {"decision": decision, "raw_artifact_path": raw_path}

    def _run_rewrite_t2i_to_i2i(self, job: Job, node, node_run: JobNodeRun) -> dict:
        """Rewrite first_frame_image (T2I) prompt into an I2I prompt."""
        t2i_prompt = self._prompt(job, "first_frame_image")
        prompt = self._prompt(job, "rewrite_t2i_to_i2i_system", required=False)
        model = self._model_for(job, node, "prompt_rewrite", "DEFAULT_PROMPT_REWRITE_MODEL")

        user_content = self._render_prompt_template(
            prompt.content if prompt else "",
            t2i=t2i_prompt.content,
            first_frame_image=t2i_prompt.content,
        )
        adapter, payload, response = self._adapter_payload(
            model,
            {
                "task": "rewrite_t2i_to_i2i",
                "t2i": t2i_prompt.content,
                "t2i_prompt": t2i_prompt.content,
                "system_prompt": "",
                "user_prompt": user_content,
                "schema_name": "rewrite_t2i_to_i2i",
                "response_schema": self._schema_for(["full_i2i_prompt"]),
            },
            job=job,
            node=node,
            param_key="prompt_rewrite",
        )
        data = self._strict_json_response(response, ["full_i2i_prompt"])
        i2i_content = data["full_i2i_prompt"]

        rewritten = {
            "i2i": i2i_content,
            "model_response": response,
        }
        raw_path = self._write_json_artifact(
            job,
            node_run,
            ["raw", "rewrite_t2i_to_i2i.json"],
            rewritten,
            "raw_response",
            "rewrite_t2i_to_i2i",
            model_id=model.model_id,
        )
        user_edit = self._get_user_edited_prompt(job, "i2i")
        if user_edit:
            PromptService.snapshot_for_job(job, user_edit)
            EventService.record(
                job,
                "PROMPT_USER_EDIT_PRESERVED",
                message=f"User-edited prompt preserved: i2i {user_edit.version}",
                node_key=node_run.node_key,
                payload={"prompt_type": "i2i", "version": user_edit.version,
                         "source": user_edit.source},
            )
            prompt = user_edit
        else:
            prompt = PromptService.create_version_for_template(
                job.template,
                {
                    "prompt_type": "i2i",
                    "job_id": job.job_id,
                    "title": "i2i generated by rewrite_t2i_to_i2i",
                    "content": i2i_content,
                    "content_format": "markdown",
                    "source": "rewrite_t2i_to_i2i",
                    "parent_version": t2i_prompt.version,
                    "activate": True,
                },
            )
            db.session.flush()
            PromptService.snapshot_for_job(job, prompt)
            PromptSyncService.sync_job_prompt_to_template(prompt, reason="rewrite_t2i_to_i2i")
            EventService.record(
                job,
                "PROMPT_VERSION_CREATED",
                message=f"Prompt version created: i2i {prompt.version}",
                node_key=node_run.node_key,
                payload={"prompt_type": "i2i", "version": prompt.version},
            )
        prompt_files = self._write_prompt_files_for_created(
            job, node_run, [prompt], "rewrite_t2i_to_i2i"
        )
        return {
            "raw_artifact_path": raw_path,
            "created_prompts": [prompt.to_dict()],
            "payload": payload,
            "adapter": adapter.__class__.__name__,
            **prompt_files,
        }

    def _run_export_manifest(self, job: Job, node, node_run: JobNodeRun) -> dict:
        active_prompts = (
            PromptVersion.query.filter_by(template_id=job.template.id, is_active=True)
            .order_by(PromptVersion.prompt_type.asc())
            .all()
        )
        events = sorted(job.events, key=lambda item: item.created_at or utc_now())[-20:]
        manifest = {
            "job": job.to_dict(),
            "source_video": job.source_video_path,
            "source_hash": job.source_hash,
            "prompt_refs": [ref.to_dict() for ref in job.prompt_refs],
            "active_prompts": [prompt.to_dict() for prompt in active_prompts],
            "artifacts": [artifact.to_dict() for artifact in job.artifacts],
            "api_tasks": [task.to_dict() for task in job.api_tasks],
            "node_runs": [run.to_dict() for run in job.node_runs],
            "budget": {
                "budget_limit": float(job.budget_limit) if job.budget_limit is not None else None,
                "cost_used": float(job.cost_used or 0),
            },
            "errors": [
                {"node_key": run.node_key, "error_message": run.error_message}
                for run in job.node_runs
                if run.error_message
            ],
            "logs_tail": [event.to_dict() for event in events],
        }
        path = StorageService.write_job_json(job.job_id, ["manifest.json"], manifest)
        artifact = ArtifactService.register_artifact(
            job,
            path,
            "manifest",
            branch_key="core",
            node_run=node_run,
        )
        EventService.record(
            job,
            "MANIFEST_EXPORTED",
            message="Manifest exported",
            node_key=node_run.node_key,
            payload={"artifact_id": artifact.artifact_id, "file_path": path},
        )
        return {"manifest_path": path, "artifact": artifact.to_dict()}
