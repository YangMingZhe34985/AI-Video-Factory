import re
from pathlib import Path

from flask import current_app
from sqlalchemy import or_

from app.api import AppError
from app.extensions import db
from app.models import Job, JobPromptRef, PromptVersion, Template
from app.services.event_service import EventService
from app.utils.time_utils import isoformat


FACTORY_PROMPT_FILES = {
    "video_understanding_system": "video_understanding_system.md",
    "video_understanding_user": "video_understanding_user.md",
    "prompt_rewrite_system": "prompt_rewrite_system.md",
    "prompt_rewrite_user": "prompt_rewrite_user.md",
    "reverse_prompts4r2v_system": "reverse_prompts4r2v_system.md",
    "rewrite_t2i_to_i2i_system": "rewrite_t2i_to_i2i_system.md",
    "failure_agent_system": "failure_agent_system.md",
    "failure_agent_user": "failure_agent_user.md",
    "t2v": "mock_t2v.md",
    "first_frame_image": "mock_first_frame_image.md",
    "r2v_flash": "mock_r2v_flash.md",
    "i2v": "mock_i2v.md",
    "negative": "mock_negative.md",
}


class PromptService:
    @staticmethod
    def get_template(template_id: str) -> Template:
        template = Template.query.filter_by(template_id=template_id).first()
        if not template and str(template_id).isdigit():
            template = db.session.get(Template, int(template_id))
        if not template:
            raise AppError("TEMPLATE_NOT_FOUND", "Template not found", 404)
        return template

    @staticmethod
    def _resolve_job(template: Template, job_id: str | None) -> Job | None:
        """Resolve job_id string to Job object, scoped to template."""
        if not job_id:
            return None
        job = Job.query.filter_by(job_id=job_id).first()
        if not job:
            raise AppError("JOB_NOT_FOUND", "Job not found", 404)
        if job.template_id != template.id:
            raise AppError("JOB_TEMPLATE_MISMATCH", "Job does not belong to this template", 400)
        return job

    @staticmethod
    def create_template(data: dict) -> Template:
        template_id = data.get("template_id")
        if template_id and Template.query.filter_by(template_id=template_id).first():
            raise AppError("INVALID_INPUT", "Template id already exists", 409)
        series = data.get("series") or data.get("series_id") or "default"
        template_kwargs = {
            "name": data["name"],
            "series": series,
            "description": data.get("description"),
            "config": data.get("config") or {},
        }
        if template_id:
            template_kwargs["template_id"] = template_id
        template = Template(**template_kwargs)
        db.session.add(template)
        db.session.flush()
        PromptService.seed_factory_prompts_for_template(template, skip_existing=True)
        db.session.commit()
        return template

    @staticmethod
    def list_templates(series_id: str | None = None) -> list[Template]:
        query = Template.query
        if series_id:
            query = query.filter(Template.series == series_id)
        return query.order_by(Template.created_at.desc()).all()

    @staticmethod
    def _next_version(template: Template, prompt_type: str, job_id: int | None = None, prompt_key: str = "default") -> str:
        """Generate next version number scoped to (template, job, type, key)."""
        query = PromptVersion.query.filter_by(
            template_id=template.id,
            prompt_type=prompt_type,
            prompt_key=prompt_key,
        )
        if job_id is not None:
            query = query.filter_by(job_id=job_id)
        else:
            query = query.filter(PromptVersion.job_id.is_(None))
        versions = query.order_by(PromptVersion.created_at.asc()).all()
        highest = 0
        for item in versions:
            match = re.match(r"^v(\d+)(?:\.\d+)?$", item.version)
            if match:
                highest = max(highest, int(match.group(1)))
        return f"v{highest + 1}.0"

    @staticmethod
    def create_version(template_id: str, data: dict) -> PromptVersion:
        template = PromptService.get_template(template_id)
        prompt = PromptService.create_version_for_template(template, data)
        db.session.commit()
        return prompt

    @staticmethod
    def create_version_for_template(template: Template, data: dict) -> PromptVersion:
        prompt_type = data["prompt_type"]
        prompt_key = data.get("prompt_key") or "default"

        # Resolve job_id
        job_db_id = None
        if data.get("job_id"):
            job = PromptService._resolve_job(template, data["job_id"])
            job_db_id = job.id if job else None

        version = data.get("version") or PromptService._next_version(
            template, prompt_type, job_id=job_db_id, prompt_key=prompt_key
        )

        # Check for duplicate version within same asset
        existing = PromptVersion.query.filter_by(
            template_id=template.id,
            prompt_type=prompt_type,
            prompt_key=prompt_key,
            version=version,
        )
        if job_db_id is not None:
            existing = existing.filter_by(job_id=job_db_id)
        else:
            existing = existing.filter(PromptVersion.job_id.is_(None))
        if existing.first():
            raise AppError(
                "VERSION_EXISTS",
                f"Version {version} already exists for this prompt asset",
                409,
            )

        if data.get("activate", True):
            # Deactivate all versions for the same asset
            q = PromptVersion.query.filter_by(
                template_id=template.id, prompt_type=prompt_type, prompt_key=prompt_key
            )
            if job_db_id is not None:
                q = q.filter_by(job_id=job_db_id)
            else:
                q = q.filter(PromptVersion.job_id.is_(None))
            q.update({"is_active": False})

        prompt = PromptVersion(
            template_id=template.id,
            job_id=job_db_id,
            prompt_type=prompt_type,
            prompt_key=prompt_key,
            version=version,
            title=data["title"],
            content=data["content"],
            content_format=data.get("content_format") or "markdown",
            is_active=data.get("activate", True),
            source=data.get("source") or "manual",
            parent_version=data.get("parent_version"),
            note=data.get("note"),
            created_by=data.get("created_by"),
        )
        db.session.add(prompt)
        return prompt

    @staticmethod
    def seed_factory_prompts(template_id: str, skip_existing: bool = True) -> list[PromptVersion]:
        template = PromptService.get_template(template_id)
        prompts = PromptService.seed_factory_prompts_for_template(
            template, skip_existing=skip_existing
        )
        db.session.commit()
        return prompts

    @staticmethod
    def seed_factory_prompts_for_template(
        template: Template, skip_existing: bool = True
    ) -> list[PromptVersion]:
        prompts_dir = Path(current_app.config["FACTORY_PROMPTS_DIR"])
        if not prompts_dir.exists():
            return []

        created = []
        for prompt_type, filename in FACTORY_PROMPT_FILES.items():
            path = prompts_dir / filename
            if not path.exists():
                continue
            existing = PromptVersion.query.filter(
                PromptVersion.template_id == template.id,
                PromptVersion.prompt_type == prompt_type,
                PromptVersion.job_id.is_(None),
                PromptVersion.prompt_key == "default",
            ).first()
            if existing and skip_existing:
                continue
            content = path.read_text(encoding="utf-8").strip()
            prompt = PromptService.create_version_for_template(
                template,
                {
                    "prompt_type": prompt_type,
                    "prompt_key": "default",
                    "version": "v1.0" if not existing else None,
                    "title": f"Factory {prompt_type}",
                    "content": content,
                    "content_format": "markdown",
                    "source": "factory_prompts",
                    "note": f"Imported from {filename}",
                    "created_by": "system",
                    "activate": True,
                },
            )
            created.append(prompt)
        return created

    # -------------------------------------------------------------------------
    # Legacy compatible query methods (scoped to template-level prompts)
    # -------------------------------------------------------------------------

    @staticmethod
    def list_versions(template_id: str, prompt_type: str, job_id: str | None = None, prompt_key: str | None = None) -> list[PromptVersion]:
        template = PromptService.get_template(template_id)
        query = PromptVersion.query.filter_by(template_id=template.id, prompt_type=prompt_type)
        if job_id is not None:
            job = PromptService._resolve_job(template, job_id)
            query = query.filter_by(job_id=job.id if job else None)
        else:
            # Legacy: only return template-level prompts when no job_id given
            query = query.filter(PromptVersion.job_id.is_(None))
        if prompt_key is not None:
            query = query.filter_by(prompt_key=prompt_key)
        return query.order_by(PromptVersion.created_at.desc()).all()

    @staticmethod
    def get_active(template_id: str, prompt_type: str, required: bool = True, job_id: str | None = None, prompt_key: str | None = None):
        template = PromptService.get_template(template_id)
        job_db_id = None
        if job_id:
            job = PromptService._resolve_job(template, job_id)
            job_db_id = job.id if job else None
        prompt = PromptService.get_active_for_template(
            template, prompt_type, job_id=job_db_id, prompt_key=prompt_key or "default"
        )
        if required and not prompt:
            raise AppError("PROMPT_NOT_FOUND", "Active prompt not found", 404)
        return prompt

    @staticmethod
    def get_active_for_template(
        template: Template,
        prompt_type: str,
        job_id: int | None = None,
        prompt_key: str = "default",
    ):
        query = PromptVersion.query.filter_by(
            template_id=template.id,
            prompt_type=prompt_type,
            prompt_key=prompt_key,
            is_active=True,
        )
        if job_id is not None:
            query = query.filter_by(job_id=job_id)
        else:
            query = query.filter(PromptVersion.job_id.is_(None))
        return query.order_by(PromptVersion.created_at.desc()).first()

    @staticmethod
    def activate(template_id: str, prompt_type: str, version: str, job_id: str | None = None, prompt_key: str = "default") -> PromptVersion:
        template = PromptService.get_template(template_id)
        job_db_id = None
        if job_id:
            job = PromptService._resolve_job(template, job_id)
            job_db_id = job.id if job else None
        q = PromptVersion.query.filter_by(
            template_id=template.id, prompt_type=prompt_type, prompt_key=prompt_key
        )
        if job_db_id is not None:
            q = q.filter_by(job_id=job_db_id)
        else:
            q = q.filter(PromptVersion.job_id.is_(None))
        prompt = q.filter_by(version=version).first()
        if not prompt:
            raise AppError("PROMPT_NOT_FOUND", "Prompt version not found", 404)
        q.filter(PromptVersion.version != version).update({"is_active": False})
        prompt.is_active = True
        db.session.commit()
        return prompt

    @staticmethod
    def rollback(
        template_id: str,
        prompt_type: str,
        version: str,
        data: dict,
        job_id: str | None = None,
        prompt_key: str = "default",
    ) -> PromptVersion:
        template = PromptService.get_template(template_id)
        job_db_id = None
        if job_id:
            job = PromptService._resolve_job(template, job_id)
            job_db_id = job.id if job else None
        q = PromptVersion.query.filter_by(
            template_id=template.id,
            prompt_type=prompt_type,
            prompt_key=prompt_key,
        )
        if job_db_id is not None:
            q = q.filter_by(job_id=job_db_id)
        else:
            q = q.filter(PromptVersion.job_id.is_(None))
        source = q.filter_by(version=version).first()
        if not source:
            raise AppError("PROMPT_NOT_FOUND", "Prompt version not found", 404)

        prompt = PromptService.create_version_for_template(
            template,
            {
                "prompt_type": prompt_type,
                "prompt_key": prompt_key,
                "job_id": data.get("job_id") or (source.job.job_id if source.job else None),
                "title": data.get("title") or f"Rollback from {version}",
                "content": source.content,
                "content_format": source.content_format,
                "source": "rollback",
                "parent_version": version,
                "note": data.get("note"),
                "created_by": data.get("created_by"),
                "activate": True,
            },
        )
        db.session.commit()
        return prompt

    @staticmethod
    def edit_version(
        template_id: str,
        prompt_type: str,
        version: str,
        data: dict,
        job_id: str | None = None,
        prompt_key: str = "default",
    ) -> PromptVersion:
        template = PromptService.get_template(template_id)
        job_db_id = None
        if job_id:
            job = PromptService._resolve_job(template, job_id)
            job_db_id = job.id if job else None
        q = PromptVersion.query.filter_by(
            template_id=template.id,
            prompt_type=prompt_type,
            prompt_key=prompt_key,
        )
        if job_db_id is not None:
            q = q.filter_by(job_id=job_db_id)
        else:
            q = q.filter(PromptVersion.job_id.is_(None))
        source = q.filter_by(version=version).first()
        if not source:
            raise AppError("PROMPT_NOT_FOUND", "Prompt version not found", 404)

        content = str(data.get("content") or "")
        if not content.strip():
            raise AppError("INVALID_INPUT", "Prompt content is required", 400)

        prompt = PromptService.create_version_for_template(
            template,
            {
                "prompt_type": prompt_type,
                "prompt_key": prompt_key,
                "job_id": data.get("job_id") or (source.job.job_id if source.job else None),
                "title": data.get("title") or f"Edited from {version}",
                "content": content,
                "content_format": data.get("content_format") or source.content_format or "markdown",
                "source": "edit",
                "parent_version": version,
                "note": data.get("note"),
                "created_by": data.get("created_by"),
                "activate": data.get("activate", True),
            },
        )
        db.session.commit()
        return prompt

    # -------------------------------------------------------------------------
    # New job-level query methods
    # -------------------------------------------------------------------------

    @staticmethod
    def list_by_job(template_id: str, job_id: str) -> list[dict]:
        """List all prompt assets (grouped by type+key) for a specific job."""
        return PromptService.list_visible_assets(template_id, job_id=job_id)

    @staticmethod
    def list_assets_by_type(template_id: str, job_id: str, prompt_type: str) -> list[dict]:
        """List all prompt assets of a specific type for a job."""
        return PromptService.list_visible_assets(template_id, job_id=job_id, prompt_type=prompt_type)

    @staticmethod
    def list_visible_assets(
        template_id: str,
        job_id: str | None = None,
        prompt_type: str | None = None,
        prompt_key: str | None = None,
    ) -> list[dict]:
        """Return prompt assets visible in Prompt Manager.

        Template-only views show every template-level prompt. Job views include
        template-level prompts, job-level PromptVersions, and job prompt refs.
        """
        template = PromptService.get_template(template_id)
        job = PromptService._resolve_job(template, job_id) if job_id else None
        assets: dict[tuple[str, str, str], dict] = {}

        prompt_query = PromptVersion.query.filter(PromptVersion.template_id == template.id)
        if prompt_type:
            prompt_query = prompt_query.filter(PromptVersion.prompt_type == prompt_type)
        if prompt_key:
            prompt_query = prompt_query.filter(PromptVersion.prompt_key == prompt_key)
        if job:
            prompt_query = prompt_query.filter(
                or_(PromptVersion.job_id.is_(None), PromptVersion.job_id == job.id)
            )
        else:
            prompt_query = prompt_query.filter(PromptVersion.job_id.is_(None))
        for prompt in prompt_query.order_by(
            PromptVersion.prompt_type.asc(),
            PromptVersion.prompt_key.asc(),
            PromptVersion.created_at.desc(),
        ):
            scope = "job" if prompt.job_id else "template"
            asset = PromptService._ensure_asset(
                assets,
                scope,
                template.template_id,
                template.name,
                template.series,
                prompt.job.job_id if prompt.job else None,
                prompt.prompt_type,
                prompt.prompt_key,
            )
            asset["versions"].append(prompt.to_dict())
            if prompt.is_active:
                asset["active_version"] = prompt.version

        if job:
            ref_query = JobPromptRef.query.filter(JobPromptRef.job_id == job.id)
            if prompt_type:
                ref_query = ref_query.filter(JobPromptRef.prompt_type == prompt_type)
            for ref in ref_query.order_by(JobPromptRef.prompt_type.asc(), JobPromptRef.created_at.desc()):
                ref_prompt_key = ref.prompt_key or (
                    ref.prompt_version.prompt_key if ref.prompt_version else "default"
                )
                if prompt_key and prompt_key != ref_prompt_key:
                    continue
                asset = PromptService._ensure_asset(
                    assets,
                    "job_snapshot",
                    template.template_id,
                    template.name,
                    template.series,
                    job.job_id,
                    ref.prompt_type,
                    ref_prompt_key,
                )
                version = PromptService._job_ref_to_version(ref, template.template_id, job.job_id, ref_prompt_key)
                asset["versions"].append(version)
                asset["active_version"] = asset["active_version"] or version["version"]

        result = list(assets.values())
        for asset in result:
            asset["versions"].sort(key=lambda item: item.get("created_at") or "", reverse=True)
            if not asset["active_version"] and asset["versions"]:
                asset["active_version"] = asset["versions"][0].get("version")
        return sorted(
            result,
            key=lambda item: (
                {"template": 0, "job": 1, "job_snapshot": 2}.get(item["scope"], 9),
                item["prompt_type"],
                item["prompt_key"],
            ),
        )

    @staticmethod
    def list_global_visible_assets(
        series_id: str | None = None,
        template_id: str | None = None,
        job_id: str | None = None,
        prompt_type: str | None = None,
        prompt_key: str | None = None,
        scope: str | None = None,
        limit: int = 500,
    ) -> list[dict]:
        """Return Prompt Manager assets across templates.

        The endpoint is designed for type-first filtering. If a job is selected,
        template-level prompts for that job's template are included alongside the
        job-level versions and snapshots, matching the template-scoped view.
        """
        assets: dict[tuple[str, str, str | None, str, str], dict] = {}
        selected_job = None
        if job_id:
            selected_job = Job.query.filter_by(job_id=job_id).first()
            if not selected_job:
                raise AppError("JOB_NOT_FOUND", "Job not found", 404)
            template_id = selected_job.template.template_id if selected_job.template else template_id

        include_prompt_versions = scope in (None, "", "template", "job")
        include_refs = scope in (None, "", "job_snapshot")

        if include_prompt_versions:
            query = PromptVersion.query.join(Template, PromptVersion.template_id == Template.id)
            if selected_job:
                query = query.filter(
                    PromptVersion.template_id == selected_job.template_id,
                    or_(PromptVersion.job_id.is_(None), PromptVersion.job_id == selected_job.id),
                )
            else:
                if series_id:
                    query = query.filter(Template.series == series_id)
                if template_id:
                    query = query.filter(Template.template_id == template_id)

            if scope == "template":
                query = query.filter(PromptVersion.job_id.is_(None))
            elif scope == "job":
                query = query.filter(PromptVersion.job_id.is_not(None))
            if prompt_type:
                query = query.filter(PromptVersion.prompt_type == prompt_type)
            if prompt_key:
                query = query.filter(PromptVersion.prompt_key == prompt_key)

            for prompt in query.order_by(PromptVersion.created_at.desc()).limit(limit).all():
                template = prompt.template
                job = prompt.job
                asset = PromptService._ensure_asset(
                    assets,
                    "job" if prompt.job_id else "template",
                    template.template_id if template else None,
                    template.name if template else None,
                    template.series if template else None,
                    job.job_id if job else None,
                    prompt.prompt_type,
                    prompt.prompt_key,
                )
                asset["versions"].append(prompt.to_dict())
                if prompt.is_active:
                    asset["active_version"] = prompt.version

        if include_refs:
            ref_query = JobPromptRef.query.join(Job, JobPromptRef.job_id == Job.id).join(
                Template, Job.template_id == Template.id
            )
            if selected_job:
                ref_query = ref_query.filter(Job.id == selected_job.id)
            else:
                if series_id:
                    ref_query = ref_query.filter(Template.series == series_id)
                if template_id:
                    ref_query = ref_query.filter(Template.template_id == template_id)
            if prompt_type:
                ref_query = ref_query.filter(JobPromptRef.prompt_type == prompt_type)
            if prompt_key:
                ref_query = ref_query.filter(JobPromptRef.prompt_key == prompt_key)

            for ref in ref_query.order_by(JobPromptRef.created_at.desc()).limit(limit).all():
                job = ref.job
                template = job.template if job else None
                ref_prompt_key = ref.prompt_key or (
                    ref.prompt_version.prompt_key if ref.prompt_version else "default"
                )
                asset = PromptService._ensure_asset(
                    assets,
                    "job_snapshot",
                    template.template_id if template else None,
                    template.name if template else None,
                    template.series if template else None,
                    job.job_id if job else None,
                    ref.prompt_type,
                    ref_prompt_key,
                )
                version = PromptService._job_ref_to_version(
                    ref,
                    template.template_id if template else None,
                    job.job_id if job else None,
                    ref_prompt_key,
                )
                asset["versions"].append(version)
                asset["active_version"] = asset["active_version"] or version["version"]

        result = list(assets.values())
        for asset in result:
            asset["versions"].sort(key=lambda item: item.get("created_at") or "", reverse=True)
            if not asset["active_version"] and asset["versions"]:
                asset["active_version"] = asset["versions"][0].get("version")
        return sorted(
            result,
            key=lambda item: (
                {"template": 0, "job": 1, "job_snapshot": 2}.get(item["scope"], 9),
                item.get("series_id") or "",
                item.get("template_id") or "",
                item.get("job_id") or "",
                item["prompt_type"],
                item["prompt_key"],
            ),
        )

    @staticmethod
    def _ensure_asset(
        assets: dict,
        scope: str,
        template_id: str | None,
        template_name: str | None,
        series_id: str | None,
        job_id: str | None,
        prompt_type: str,
        prompt_key: str,
    ) -> dict:
        key = (scope, template_id or "", job_id, prompt_type, prompt_key)
        if key not in assets:
            assets[key] = {
                "scope": scope,
                "template_id": template_id,
                "template_name": template_name,
                "series_id": series_id or "default",
                "job_id": job_id,
                "prompt_type": prompt_type,
                "prompt_key": prompt_key,
                "active_version": None,
                "versions": [],
            }
        return assets[key]

    @staticmethod
    def _job_ref_to_version(
        ref: JobPromptRef,
        template_id: str,
        job_id: str,
        prompt_key: str,
    ) -> dict:
        return {
            "id": f"ref:{ref.ref_id}",
            "prompt_id": ref.ref_id,
            "template_id": template_id,
            "job_id": job_id,
            "prompt_type": ref.prompt_type,
            "prompt_key": prompt_key,
            "version": ref.version,
            "title": ref.title,
            "content": ref.content_snapshot,
            "content_format": "markdown",
            "is_active": True,
            "source": "job_snapshot",
            "read_only": True,
            "created_at": isoformat(ref.created_at),
            "updated_at": isoformat(ref.created_at),
        }

    @staticmethod
    def list_versions_for_asset(
        template_id: str, job_id: str, prompt_type: str, prompt_key: str
    ) -> list[PromptVersion]:
        template = PromptService.get_template(template_id)
        job = PromptService._resolve_job(template, job_id)
        return (
            PromptVersion.query.filter_by(
                template_id=template.id,
                job_id=job.id,
                prompt_type=prompt_type,
                prompt_key=prompt_key,
            )
            .order_by(PromptVersion.created_at.desc())
            .all()
        )

    @staticmethod
    def get_active_for_asset(
        template_id: str, job_id: str, prompt_type: str, prompt_key: str
    ) -> PromptVersion:
        template = PromptService.get_template(template_id)
        job = PromptService._resolve_job(template, job_id)
        prompt = (
            PromptVersion.query.filter_by(
                template_id=template.id,
                job_id=job.id,
                prompt_type=prompt_type,
                prompt_key=prompt_key,
                is_active=True,
            )
            .order_by(PromptVersion.created_at.desc())
            .first()
        )
        if not prompt:
            raise AppError("PROMPT_NOT_FOUND", "Active prompt not found for this asset", 404)
        return prompt

    @staticmethod
    def snapshot_for_job(job: Job, prompt: PromptVersion) -> JobPromptRef:
        existing = JobPromptRef.query.filter_by(
            job_id=job.id,
            prompt_type=prompt.prompt_type,
            prompt_key=prompt.prompt_key,
            version=prompt.version,
        ).first()
        if existing:
            return existing
        ref = JobPromptRef(
            job_id=job.id,
            prompt_version_id=prompt.id,
            prompt_type=prompt.prompt_type,
            prompt_key=prompt.prompt_key,
            version=prompt.version,
            title=prompt.title,
            content_snapshot=prompt.content,
        )
        db.session.add(ref)
        EventService.record(
            job,
            "PROMPT_SNAPSHOT_CREATED",
            message=f"Prompt snapshot saved: {prompt.prompt_type} {prompt.version}",
            payload={"prompt_type": prompt.prompt_type, "version": prompt.version},
        )
        return ref
