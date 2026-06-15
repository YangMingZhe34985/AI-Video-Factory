import re
import zipfile
from pathlib import Path

from sqlalchemy import desc

from app.api import AppError
from app.models.artifact import Artifact
from app.models.job import Job
from app.models.job_prompt_ref import JobPromptRef
from app.models.prompt_version import PromptVersion
from app.services.prompt_service import PromptService
from app.services.prompt_sync_service import PromptSyncService
from app.services.storage_service import StorageService
from app.utils.files import ensure_dir
from app.utils.json_utils import dump_pretty
from app.utils.time_utils import isoformat, utc_now


class TemplatePackageService:
    VIDEO_PRIORITY = (
        "i2v_video",
        "t2v_video",
        "i2i_test_video",
        "r2v_flash_video",
        "r2v_flash_videos",
    )

    PROMPT_FILE_NAMES = {
        "i2i": "i2i.md",
        "i2v": "i2v.md",
        "r2v_flash": "r2v.md",
    }

    @staticmethod
    def create_package(template_id: str) -> dict:
        template = PromptService.get_template(template_id)
        selected_prompts = TemplatePackageService._select_prompts(template)
        selected_video = TemplatePackageService._select_video(template)

        if not selected_prompts and not selected_video:
            raise AppError(
                "NO_TEMPLATE_PACKABLE_CONTENT",
                "No packable prompt or video was found for this template",
                400,
            )

        package_path = TemplatePackageService.package_path(template.template_id)
        ensure_dir(package_path.parent)
        packaged_at = utc_now()
        package_status = "full" if selected_prompts and selected_video else "partial"
        manifest = TemplatePackageService._manifest(
            template,
            selected_prompts,
            selected_video,
            package_status,
            packaged_at,
        )

        with zipfile.ZipFile(package_path, "w", zipfile.ZIP_DEFLATED) as archive:
            for prompt in selected_prompts:
                archive.writestr(
                    f"prompts/{prompt['file_name']}",
                    prompt.get("content") or "",
                )
            if selected_video:
                source = StorageService.resolve(selected_video.file_path)
                archive.write(source, TemplatePackageService._video_zip_path(selected_video))
            archive.writestr("package_manifest.json", dump_pretty(manifest))

        return {
            "download_url": f"/api/templates/{template.template_id}/package/download",
            "package_status": package_status,
            "included_counts": manifest["included_counts"],
            "package_file": package_path.name,
            "packaged_at": isoformat(packaged_at),
        }

    @staticmethod
    def package_path(template_id: str) -> Path:
        safe_id = TemplatePackageService._safe_file_part(template_id)
        return (
            StorageService.root()
            / "templates"
            / safe_id
            / "packages"
            / f"template_{safe_id}_package.zip"
        )

    @staticmethod
    def get_package_path(template_id: str) -> Path:
        PromptService.get_template(template_id)
        package_path = TemplatePackageService.package_path(template_id)
        if not package_path.exists():
            raise AppError(
                "TEMPLATE_PACKAGE_NOT_FOUND",
                "Template package has not been generated yet",
                404,
            )
        return package_path

    @staticmethod
    def _select_prompts(template) -> list[dict]:
        prompts = []
        i2i = TemplatePackageService._resolve_prompt(template, "i2i")
        i2v = TemplatePackageService._resolve_prompt(template, "i2v")
        if i2i:
            prompts.append(i2i)
        if i2v:
            prompts.append(i2v)
        if prompts:
            return prompts

        r2v = TemplatePackageService._resolve_prompt(template, "r2v_flash")
        return [r2v] if r2v else []

    @staticmethod
    def _resolve_prompt(template, prompt_type: str) -> dict | None:
        resolvers = (
            TemplatePackageService._template_active_prompt,
            TemplatePackageService._template_latest_prompt,
            TemplatePackageService._job_active_prompt,
            TemplatePackageService._job_prompt_ref,
        )
        for resolver in resolvers:
            result = resolver(template, prompt_type)
            if result and str(result.get("content") or "").strip():
                result["file_name"] = TemplatePackageService.PROMPT_FILE_NAMES[prompt_type]
                return result
        return None

    @staticmethod
    def _template_active_prompt(template, prompt_type: str) -> dict | None:
        query = (
            PromptVersion.query.filter(
                PromptVersion.template_id == template.id,
                PromptVersion.job_id.is_(None),
                PromptVersion.prompt_type == prompt_type,
                PromptVersion.is_active.is_(True),
                PromptVersion.source != "factory_prompts",
            )
            .order_by(desc(PromptVersion.created_at))
        )
        prompt = TemplatePackageService._first_non_empty_prompt(query)
        return TemplatePackageService._prompt_version_entry(prompt, "template_active")

    @staticmethod
    def _template_latest_prompt(template, prompt_type: str) -> dict | None:
        query = (
            PromptVersion.query.filter(
                PromptVersion.template_id == template.id,
                PromptVersion.job_id.is_(None),
                PromptVersion.prompt_type == prompt_type,
                PromptVersion.source != "factory_prompts",
            )
            .order_by(desc(PromptVersion.created_at))
        )
        prompt = TemplatePackageService._first_non_empty_prompt(query)
        return TemplatePackageService._prompt_version_entry(prompt, "template_latest")

    @staticmethod
    def _job_active_prompt(template, prompt_type: str) -> dict | None:
        query = (
            PromptVersion.query.join(Job, PromptVersion.job_id == Job.id)
            .filter(
                Job.template_id == template.id,
                PromptVersion.prompt_type == prompt_type,
                PromptVersion.is_active.is_(True),
            )
            .order_by(desc(PromptVersion.created_at))
        )
        prompt = TemplatePackageService._first_non_empty_prompt(query)
        return TemplatePackageService._prompt_version_entry(prompt, "job_active")

    @staticmethod
    def _job_prompt_ref(template, prompt_type: str) -> dict | None:
        refs = (
            JobPromptRef.query.join(Job, JobPromptRef.job_id == Job.id)
            .filter(
                Job.template_id == template.id,
                JobPromptRef.prompt_type == prompt_type,
            )
            .order_by(desc(JobPromptRef.created_at))
            .limit(50)
            .all()
        )
        ref = next((item for item in refs if str(item.content_snapshot or "").strip()), None)
        if not ref:
            return None
        return {
            "prompt_type": ref.prompt_type,
            "prompt_key": ref.prompt_key,
            "version": ref.version,
            "title": ref.title,
            "content": ref.content_snapshot,
            "source": "job_snapshot",
            "source_id": ref.ref_id,
            "job_id": ref.job.job_id if ref.job else None,
            "created_at": isoformat(ref.created_at),
        }

    @staticmethod
    def _prompt_version_entry(prompt: PromptVersion | None, source: str) -> dict | None:
        if not prompt:
            return None
        return {
            "prompt_type": prompt.prompt_type,
            "prompt_key": prompt.prompt_key,
            "version": prompt.version,
            "title": prompt.title,
            "content": prompt.content,
            "source": source,
            "source_id": prompt.prompt_id,
            "job_id": prompt.job.job_id if prompt.job else None,
            "created_at": isoformat(prompt.created_at),
        }

    @staticmethod
    def _first_non_empty_prompt(query) -> PromptVersion | None:
        for prompt in query.limit(50).all():
            if not PromptSyncService.is_usable_business_prompt(prompt):
                continue
            if str(prompt.content or "").strip():
                return prompt
        return None

    @staticmethod
    def _select_video(template) -> Artifact | None:
        for artifact_type in TemplatePackageService.VIDEO_PRIORITY:
            artifacts = (
                Artifact.query.join(Job, Artifact.job_id == Job.id)
                .filter(
                    Job.template_id == template.id,
                    Artifact.artifact_type == artifact_type,
                )
                .order_by(desc(Artifact.created_at))
                .all()
            )
            for artifact in artifacts:
                if StorageService.resolve(artifact.file_path).exists():
                    return artifact
        return None

    @staticmethod
    def _video_zip_path(artifact: Artifact) -> str:
        safe_name = Path(artifact.file_name or artifact.file_path).name
        return f"video/{artifact.artifact_type}_{artifact.artifact_id}_{safe_name}"

    @staticmethod
    def _manifest(template, prompts: list[dict], video: Artifact | None, package_status: str, packaged_at) -> dict:
        return {
            "template_id": template.template_id,
            "template_name": template.name,
            "package_status": package_status,
            "packaged_at": isoformat(packaged_at),
            "included_prompt_types": [prompt["prompt_type"] for prompt in prompts],
            "included_prompts": [
                {
                    key: value
                    for key, value in prompt.items()
                    if key not in {"content"}
                }
                for prompt in prompts
            ],
            "included_video_artifact": video.to_dict() if video else None,
            "included_counts": {
                "prompts": len(prompts),
                "videos": 1 if video else 0,
            },
        }

    @staticmethod
    def _safe_file_part(value: str | None) -> str:
        cleaned = re.sub(r"[^A-Za-z0-9_.-]+", "_", str(value or "").strip())
        return cleaned.strip("._") or "default"
