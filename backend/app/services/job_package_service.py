import zipfile
from pathlib import Path

from app.api import AppError
from app.extensions import db
from app.models import Artifact, Job, PromptVersion
from app.services.event_service import EventService
from app.services.storage_service import StorageService
from app.utils.files import ensure_dir
from app.utils.json_utils import dump_pretty, to_jsonable
from app.utils.time_utils import isoformat, utc_now


class JobPackageService:
    EXCLUDED_TYPES = {
        "job_package",
        "request_payload",
        "api_response",
        "task_meta",
        "raw_response",
        "manifest",
        "i2i_test_batch",
    }
    R2V_VIDEO_TYPES = {"r2v_flash_video", "r2v_flash_videos"}
    I2I_IMAGE_TYPES = {"i2i_test_source_image", "i2i_test_first_frame_image"}

    @staticmethod
    def create_or_refresh(job: Job) -> dict:
        plan = JobPackageService._build_package_plan(job)
        prompt_payload = JobPackageService._prompt_payload(job, plan["prompt_types"])
        prompt_file_entries = JobPackageService._individual_prompt_files(prompt_payload)

        if (
            not plan["video_artifacts"]
            and not plan["image_artifacts"]
            and not prompt_payload["prompt_refs"]
            and not prompt_payload["active_prompts"]
        ):
            raise AppError(
                "NO_PACKABLE_CONTENT",
                "No packable video, image, or job prompt snapshot was found for this job",
                400,
            )

        package_status = "full" if plan["video_artifacts"] else "partial"
        package_dir = ensure_dir(StorageService.job_dir(job.job_id, "packages"))
        package_name = f"job_{job.job_id}_package.zip"
        package_path = package_dir / package_name
        manifest = JobPackageService._package_manifest(
            job,
            plan["video_artifacts"],
            plan["image_artifacts"],
            prompt_payload,
            prompt_file_entries,
            package_status,
        )

        with zipfile.ZipFile(package_path, "w", compression=zipfile.ZIP_DEFLATED) as archive:
            for artifact in plan["video_artifacts"]:
                JobPackageService._write_artifact(archive, artifact, "final")
            for artifact in plan["image_artifacts"]:
                JobPackageService._write_artifact(archive, artifact, "assets")
            archive.writestr("prompts/prompts.json", dump_pretty(prompt_payload))
            for entry in prompt_file_entries:
                archive.writestr(f"prompts/{entry['file_name']}", entry["content"])
            archive.writestr("package_manifest.json", dump_pretty(manifest))

        relative_path = StorageService.relative_path(package_path)
        artifact = JobPackageService._upsert_package_artifact(
            job,
            relative_path,
            {
                "packaged_at": manifest["packaged_at"],
                "package_status": package_status,
                "included_artifact_ids": manifest["included_artifact_ids"],
                "included_video_artifact_ids": manifest["included_video_artifact_ids"],
                "included_image_artifact_ids": manifest["included_image_artifact_ids"],
                "included_prompt_types": manifest["included_prompt_types"],
                "included_prompt_files": manifest["included_prompt_files"],
                "selected_final_artifact_id": manifest["selected_final_artifact_id"],
                "included_counts": manifest["included_counts"],
            },
        )
        EventService.record(
            job,
            "JOB_PACKAGE_EXPORTED",
            message="Job package exported",
            payload={
                "artifact_id": artifact.artifact_id,
                "package_status": package_status,
                "included_counts": manifest["included_counts"],
                "included_prompt_types": manifest["included_prompt_types"],
            },
        )
        db.session.commit()
        return {
            "artifact": artifact.to_dict(),
            "download_url": f"/api/artifacts/{artifact.artifact_id}/download",
            "package_status": package_status,
            "included_counts": manifest["included_counts"],
        }

    @staticmethod
    def _build_package_plan(job: Job) -> dict:
        i2v_video = JobPackageService._latest_existing_artifact(job, "i2v_video")
        t2v_video = JobPackageService._latest_existing_artifact(job, "t2v_video")
        i2i_videos = JobPackageService._existing_artifacts(job, ["i2i_test_video"])
        r2v_videos = JobPackageService._existing_artifacts(job, JobPackageService.R2V_VIDEO_TYPES)
        first_frame = JobPackageService._latest_existing_artifact(job, "first_frame_image")
        i2i_images = JobPackageService._existing_artifacts(job, JobPackageService.I2I_IMAGE_TYPES)
        reference_images = JobPackageService._existing_artifacts(job, ["reference_image"])

        has_i2v = i2v_video is not None
        has_i2i = bool(
            i2i_videos
            or i2i_images
            or JobPackageService._node_succeeded(job, "rewrite_t2i_to_i2i")
        )
        has_t2v = t2v_video is not None
        has_r2v = bool(r2v_videos)
        r2v_only = has_r2v and not has_i2v and not has_i2i and not has_t2v

        video_artifacts = []
        image_artifacts = []
        prompt_types = []

        if has_i2v:
            video_artifacts.append(i2v_video)
            if first_frame:
                image_artifacts.append(first_frame)
            prompt_types.append("i2v")

        if has_i2i:
            video_artifacts.extend(i2i_videos)
            image_artifacts.extend(i2i_images)
            prompt_types.append("i2i")

        if not has_i2v and not has_i2i and has_t2v:
            video_artifacts.append(t2v_video)

        if r2v_only:
            video_artifacts.extend(r2v_videos)
            image_artifacts.extend(reference_images)
            prompt_types.append("r2v_flash")

        return {
            "video_artifacts": JobPackageService._dedupe_artifacts(video_artifacts),
            "image_artifacts": JobPackageService._dedupe_artifacts(image_artifacts)[:30],
            "prompt_types": JobPackageService._dedupe_strings(prompt_types),
        }

    @staticmethod
    def _latest_existing_artifact(job: Job, artifact_type: str) -> Artifact | None:
        candidates = (
            Artifact.query.filter_by(job_id=job.id, artifact_type=artifact_type)
            .order_by(Artifact.created_at.desc())
            .all()
        )
        for artifact in candidates:
            if JobPackageService._artifact_file_exists(artifact):
                return artifact
        return None

    @staticmethod
    def _existing_artifacts(job: Job, artifact_types) -> list[Artifact]:
        candidates = (
            Artifact.query.filter(Artifact.job_id == job.id)
            .filter(Artifact.artifact_type.in_(list(artifact_types)))
            .order_by(Artifact.created_at.asc())
            .all()
        )
        return [artifact for artifact in candidates if JobPackageService._artifact_file_exists(artifact)]

    @staticmethod
    def _artifact_file_exists(artifact: Artifact) -> bool:
        if artifact.artifact_type in JobPackageService.EXCLUDED_TYPES:
            return False
        return StorageService.resolve(artifact.file_path).exists()

    @staticmethod
    def _node_succeeded(job: Job, node_key: str) -> bool:
        return any(
            run.node_key == node_key and run.status == "success"
            for run in (job.node_runs or [])
        )

    @staticmethod
    def _write_artifact(archive: zipfile.ZipFile, artifact: Artifact, prefix: str) -> None:
        source = StorageService.resolve(artifact.file_path)
        safe_name = Path(artifact.file_name or source.name).name
        archive.write(source, f"{prefix}/{artifact.artifact_type}_{artifact.artifact_id}_{safe_name}")

    @staticmethod
    def _prompt_payload(job: Job, prompt_types: list[str]) -> dict:
        selected_types = set(prompt_types)
        prompt_refs = [
            ref.to_dict()
            for ref in job.prompt_refs
            if ref.prompt_type in selected_types
        ]
        covered_types = {ref["prompt_type"] for ref in prompt_refs}
        active_prompts = []
        for prompt_type in sorted(selected_types - covered_types):
            prompt = JobPackageService._active_prompt_for_job(job, prompt_type)
            if prompt:
                active_prompts.append(prompt)
        return {
            "included_prompt_types": sorted(selected_types),
            "prompt_refs": prompt_refs,
            "active_prompts": [prompt.to_dict() for prompt in active_prompts],
        }

    @staticmethod
    def _individual_prompt_files(payload: dict) -> list[dict]:
        latest_by_type = {}
        for ref in payload.get("prompt_refs") or []:
            JobPackageService._keep_latest_prompt_entry(
                latest_by_type,
                {
                    "prompt_type": ref.get("prompt_type"),
                    "prompt_key": ref.get("prompt_key") or "default",
                    "version": ref.get("version"),
                    "created_at": ref.get("created_at") or "",
                    "content": ref.get("content_snapshot") or "",
                },
            )
        for prompt in payload.get("active_prompts") or []:
            JobPackageService._keep_latest_prompt_entry(
                latest_by_type,
                {
                    "prompt_type": prompt.get("prompt_type"),
                    "prompt_key": prompt.get("prompt_key") or "default",
                    "version": prompt.get("version"),
                    "created_at": prompt.get("created_at") or "",
                    "content": prompt.get("content") or "",
                },
            )
        result = []
        for entry in latest_by_type.values():
            if not entry["prompt_type"] or not str(entry["content"]).strip():
                continue
            result.append(
                {
                    **entry,
                    "file_name": JobPackageService._prompt_file_name(
                        entry["prompt_type"], entry["prompt_key"]
                    ),
                }
            )
        return sorted(result, key=lambda item: item["file_name"])

    @staticmethod
    def _keep_latest_prompt_entry(target: dict, entry: dict) -> None:
        prompt_type = entry.get("prompt_type")
        if not prompt_type:
            return
        current = target.get(prompt_type)
        if not current or str(entry.get("created_at") or "") >= str(current.get("created_at") or ""):
            target[prompt_type] = entry

    @staticmethod
    def _prompt_file_name(prompt_type: str, prompt_key: str | None = "default") -> str:
        stem_map = {
            "t2v": "reverse_t2v",
            "first_frame_image": "first_frame_image",
            "i2v": "i2v",
            "r2v_flash": "r2v_flash",
            "i2i": "i2i",
        }
        stem = stem_map.get(prompt_type, prompt_type)
        if not prompt_key or prompt_key == "default":
            return f"{JobPackageService._safe_file_part(stem)}.md"
        return (
            f"{JobPackageService._safe_file_part(stem)}_"
            f"{JobPackageService._safe_file_part(prompt_key)}.md"
        )

    @staticmethod
    def _safe_file_part(value: str) -> str:
        cleaned = "".join(char if char.isalnum() or char in {"-", "_"} else "_" for char in str(value))
        return cleaned.strip("_") or "prompt"

    @staticmethod
    def _active_prompt_for_job(job: Job, prompt_type: str) -> PromptVersion | None:
        prompt = (
            PromptVersion.query.filter_by(
                template_id=job.template_id,
                job_id=job.id,
                prompt_type=prompt_type,
                is_active=True,
            )
            .order_by(PromptVersion.created_at.desc())
            .first()
        )
        if prompt:
            return prompt
        return (
            PromptVersion.query.filter(
                PromptVersion.template_id == job.template_id,
                PromptVersion.job_id.is_(None),
                PromptVersion.prompt_type == prompt_type,
                PromptVersion.is_active.is_(True),
            )
            .order_by(PromptVersion.created_at.desc())
            .first()
        )

    @staticmethod
    def _package_manifest(
        job: Job,
        video_artifacts: list[Artifact],
        image_artifacts: list[Artifact],
        prompt_payload: dict,
        prompt_file_entries: list[dict],
        package_status: str,
    ) -> dict:
        included_artifacts = video_artifacts + image_artifacts
        return {
            "job_id": job.job_id,
            "template_id": job.external_template_id,
            "source_video": job.source_video_path,
            "source_hash": job.source_hash,
            "packaged_at": isoformat(utc_now()),
            "package_status": package_status,
            "selected_final_artifact_id": video_artifacts[0].artifact_id if video_artifacts else None,
            "included_artifact_ids": [artifact.artifact_id for artifact in included_artifacts],
            "included_video_artifact_ids": [artifact.artifact_id for artifact in video_artifacts],
            "included_image_artifact_ids": [artifact.artifact_id for artifact in image_artifacts],
            "included_prompt_types": prompt_payload["included_prompt_types"],
            "included_prompt_files": [
                {
                    "prompt_type": entry["prompt_type"],
                    "prompt_key": entry["prompt_key"],
                    "version": entry["version"],
                    "file_name": entry["file_name"],
                }
                for entry in prompt_file_entries
            ],
            "included_artifacts": [artifact.to_dict() for artifact in included_artifacts],
            "included_counts": {
                "videos": len(video_artifacts),
                "images": len(image_artifacts),
                "prompts": len(prompt_payload["prompt_refs"]) + len(prompt_payload["active_prompts"]),
            },
        }

    @staticmethod
    def _upsert_package_artifact(job: Job, file_path: str, metadata: dict) -> Artifact:
        resolved = StorageService.resolve(file_path)
        artifact = (
            Artifact.query.filter_by(job_id=job.id, artifact_type="job_package", branch_key="package")
            .order_by(Artifact.created_at.desc())
            .first()
        )
        if artifact:
            artifact.file_path = file_path
            artifact.file_name = Path(file_path).name
            artifact.mime_type = "application/zip"
            artifact.size = resolved.stat().st_size if resolved.exists() else 0
            artifact.meta = to_jsonable(metadata)
            return artifact

        artifact = Artifact(
            job_id=job.id,
            file_path=file_path,
            file_name=Path(file_path).name,
            mime_type="application/zip",
            size=resolved.stat().st_size if resolved.exists() else 0,
            artifact_type="job_package",
            branch_key="package",
            meta=to_jsonable(metadata),
        )
        db.session.add(artifact)
        db.session.flush()
        return artifact

    @staticmethod
    def _dedupe_artifacts(artifacts: list[Artifact]) -> list[Artifact]:
        result = []
        seen = set()
        for artifact in artifacts:
            if not artifact or artifact.artifact_id in seen:
                continue
            seen.add(artifact.artifact_id)
            result.append(artifact)
        return result

    @staticmethod
    def _dedupe_strings(values: list[str]) -> list[str]:
        result = []
        seen = set()
        for value in values:
            if value in seen:
                continue
            seen.add(value)
            result.append(value)
        return result
