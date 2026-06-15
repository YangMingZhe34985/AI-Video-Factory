import re

from app.extensions import db
from app.models import PromptVersion
from app.services.event_service import EventService


BUSINESS_PROMPT_TYPES = {
    "t2v",
    "first_frame_image",
    "i2v",
    "i2i",
    "r2v_flash",
    "negative",
}


class PromptSyncService:
    """Synchronize job-level business prompts back to template-level active prompts."""

    @staticmethod
    def is_business_prompt(prompt_type: str | None) -> bool:
        return str(prompt_type or "") in BUSINESS_PROMPT_TYPES

    @staticmethod
    def is_business_factory_mock(prompt: PromptVersion | None) -> bool:
        return bool(
            prompt
            and PromptSyncService.is_business_prompt(prompt.prompt_type)
            and prompt.job_id is None
            and prompt.source == "factory_prompts"
        )

    @staticmethod
    def is_usable_business_prompt(prompt: PromptVersion | None) -> bool:
        if not prompt:
            return False
        if PromptSyncService.is_business_factory_mock(prompt):
            return False
        return bool(str(prompt.content or "").strip())

    @staticmethod
    def sync_job_prompt_to_template(
        prompt: PromptVersion | None,
        reason: str = "prompt_updated",
    ) -> PromptVersion | None:
        if not prompt or prompt.job_id is None:
            return None
        if not PromptSyncService.is_business_prompt(prompt.prompt_type):
            return None
        if not str(prompt.content or "").strip():
            return None

        job = prompt.job
        template = prompt.template
        if not job or not template:
            return None

        existing = (
            PromptVersion.query.filter(
                PromptVersion.template_id == template.id,
                PromptVersion.job_id.is_(None),
                PromptVersion.prompt_type == prompt.prompt_type,
                PromptVersion.prompt_key == prompt.prompt_key,
                PromptVersion.source == "synced_from_job",
                PromptVersion.is_active.is_(True),
            )
            .order_by(PromptVersion.created_at.desc())
            .first()
        )
        if (
            existing
            and existing.content == prompt.content
            and f"source_prompt_id={prompt.prompt_id}" in str(existing.note or "")
        ):
            return existing

        PromptVersion.query.filter(
            PromptVersion.template_id == template.id,
            PromptVersion.job_id.is_(None),
            PromptVersion.prompt_type == prompt.prompt_type,
            PromptVersion.prompt_key == prompt.prompt_key,
        ).update({"is_active": False})

        synced = PromptVersion(
            template_id=template.id,
            job_id=None,
            prompt_type=prompt.prompt_type,
            prompt_key=prompt.prompt_key,
            version=PromptSyncService._next_template_version(
                template.id, prompt.prompt_type, prompt.prompt_key
            ),
            title=f"Synced {prompt.prompt_type} from {job.job_id}",
            content=prompt.content,
            content_format=prompt.content_format or "markdown",
            is_active=True,
            source="synced_from_job",
            parent_version=prompt.version,
            note=(
                f"Synced from job_id={job.job_id}; "
                f"source_prompt_id={prompt.prompt_id}; "
                f"source_version={prompt.version}; reason={reason}"
            ),
            created_by=prompt.created_by or "system",
        )
        db.session.add(synced)
        db.session.flush()
        EventService.record(
            job,
            "TEMPLATE_PROMPT_SYNCED",
            message=f"Template prompt synced: {prompt.prompt_type} {synced.version}",
            payload={
                "prompt_type": prompt.prompt_type,
                "prompt_key": prompt.prompt_key,
                "job_prompt_id": prompt.prompt_id,
                "job_prompt_version": prompt.version,
                "template_prompt_id": synced.prompt_id,
                "template_prompt_version": synced.version,
                "reason": reason,
            },
        )
        return synced

    @staticmethod
    def _next_template_version(template_pk: int, prompt_type: str, prompt_key: str) -> str:
        versions = (
            PromptVersion.query.filter(
                PromptVersion.template_id == template_pk,
                PromptVersion.job_id.is_(None),
                PromptVersion.prompt_type == prompt_type,
                PromptVersion.prompt_key == prompt_key,
            )
            .order_by(PromptVersion.created_at.asc())
            .all()
        )
        highest = 0
        for item in versions:
            match = re.match(r"^v(\d+)(?:\.\d+)?$", item.version or "")
            if match:
                highest = max(highest, int(match.group(1)))
        return f"v{highest + 1}.0"
