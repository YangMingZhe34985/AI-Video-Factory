from pathlib import Path

from sqlalchemy import or_

from app.api import AppError
from app.extensions import db
from app.models import ApiTask, Artifact, Job, JobNodeRun, Template
from app.services.event_service import EventService
from app.services.storage_service import StorageService
from app.utils.files import guess_mime_type


class ArtifactService:
    PROCESS_ARTIFACT_TYPES = {
        "request_payload",
        "api_response",
        "task_meta",
        "raw_response",
        "manifest",
        "i2i_test_batch",
    }

    @staticmethod
    def register_artifact(
        job: Job,
        file_path: str,
        artifact_type: str,
        branch_key: str | None = None,
        node_run: JobNodeRun | None = None,
        api_task: ApiTask | None = None,
        model_id: str | None = None,
        prompt_version: str | None = None,
        metadata: dict | None = None,
    ) -> Artifact:
        resolved = StorageService.resolve(file_path)
        artifact = Artifact(
            job_id=job.id,
            node_run_id=node_run.id if node_run else None,
            api_task_id=api_task.id if api_task else None,
            file_path=file_path,
            file_name=Path(file_path).name,
            mime_type=guess_mime_type(resolved),
            size=resolved.stat().st_size if resolved.exists() else 0,
            artifact_type=artifact_type,
            branch_key=branch_key,
            model_id=model_id,
            prompt_version=prompt_version,
            meta=metadata or {},
        )
        db.session.add(artifact)
        db.session.flush()
        EventService.record(
            job,
            "ARTIFACT_CREATED",
            message=f"Artifact created: {artifact_type}",
            node_key=node_run.node_key if node_run else None,
            payload={"file_path": file_path, "artifact_type": artifact_type},
        )
        return artifact

    @staticmethod
    def list_for_job(job: Job) -> list[dict]:
        result = []
        for artifact in job.artifacts:
            result.append(ArtifactService._to_display_dict(artifact))
        return ArtifactService.sort_for_display(result)

    @staticmethod
    def get_by_artifact_id(artifact_id: str) -> Artifact:
        artifact = Artifact.query.filter_by(artifact_id=artifact_id).first()
        if not artifact and str(artifact_id).isdigit():
            artifact = db.session.get(Artifact, int(artifact_id))
        if not artifact:
            raise AppError("ARTIFACT_NOT_FOUND", "Artifact not found", 404)
        return artifact

    @staticmethod
    def latest_for_job(job: Job, artifact_type: str) -> Artifact | None:
        return (
            Artifact.query.filter_by(job_id=job.id, artifact_type=artifact_type)
            .order_by(Artifact.created_at.desc())
            .first()
        )

    @staticmethod
    def search_artifacts(
        job_id: str | None = None,
        template_id: str | None = None,
        template_name: str | None = None,
        artifact_type: str | None = None,
        branch_key: str | None = None,
        search: str | None = None,
        series_id: str | None = None,
    ) -> list[dict]:
        query = Artifact.query.join(Job).join(Template)

        if series_id:
            query = query.filter(Template.series == series_id.strip())

        if job_id:
            value = job_id.strip()
            query = query.filter(
                or_(
                    Job.job_id.contains(value),
                    Job.job_name.contains(value),
                )
            )

        if template_id:
            query = query.filter(
                or_(
                    Template.template_id == template_id.strip(),
                    Template.template_id.contains(template_id.strip()),
                )
            )

        if template_name:
            query = query.filter(Template.name.contains(template_name.strip()))

        if artifact_type:
            kind = artifact_type.strip()
            if kind == "image":
                query = query.filter(
                    or_(Artifact.mime_type.startswith("image/"), Artifact.artifact_type.contains("image"))
                )
            elif kind == "video":
                query = query.filter(
                    or_(Artifact.mime_type.startswith("video/"), Artifact.artifact_type.contains("video"))
                )
            elif kind == "json":
                query = query.filter(
                    or_(Artifact.mime_type == "application/json", Artifact.file_name.endswith(".json"))
                )
            else:
                query = query.filter(Artifact.artifact_type == kind)

        if branch_key:
            query = query.filter(Artifact.branch_key == branch_key.strip())

        if search:
            value = search.strip()
            query = query.filter(
                or_(
                    Job.job_id.contains(value),
                    Job.job_name.contains(value),
                    Template.name.contains(value),
                    Template.template_id.contains(value),
                    Artifact.file_name.contains(value),
                )
            )

        artifacts = query.order_by(Artifact.created_at.desc()).limit(200).all()
        result = []
        for artifact in artifacts:
            result.append(ArtifactService._to_display_dict(artifact))
        return ArtifactService.sort_for_display(result)

    @staticmethod
    def sort_for_display(artifacts: list[dict]) -> list[dict]:
        return sorted(
            artifacts,
            key=lambda item: (
                item.get("artifact_priority", 900),
                -(int(item.get("id") or 0)),
            ),
            reverse=False,
        )

    @staticmethod
    def _to_display_dict(artifact: Artifact) -> dict:
        data = artifact.to_dict()
        job = artifact.job
        template = job.template if job else None
        data["job_id"] = job.job_id if job else None
        data["job_name"] = job.job_name if job else None
        data["template_id"] = template.template_id if template else None
        data["template_name"] = template.name if template else None
        data["series_id"] = (template.series if template else None) or "default"
        priority, group = ArtifactService._display_priority(data)
        data["artifact_priority"] = priority
        data["artifact_group"] = group
        return data

    @staticmethod
    def _display_priority(data: dict) -> tuple[int, str]:
        artifact_type = str(data.get("artifact_type") or "")
        mime_type = str(data.get("mime_type") or "")
        file_name = str(data.get("file_name") or data.get("filename") or "")
        if mime_type.startswith("image/") or artifact_type.endswith("_image") or "image" in artifact_type:
            return 10, "image"
        if mime_type.startswith("video/") or artifact_type.endswith("_video") or "video" in artifact_type:
            return 20, "video"
        if artifact_type == "job_package" or mime_type == "application/zip":
            return 25, "package"
        if "prompt" in artifact_type:
            return 30, "prompt"
        if artifact_type == "manifest":
            return 35, "manifest"
        if artifact_type in ArtifactService.PROCESS_ARTIFACT_TYPES or file_name.endswith(".json"):
            return 90, "process"
        return 50, "other"
