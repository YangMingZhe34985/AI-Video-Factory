"""Visibility rules for public lists containing private Agent job material."""
from sqlalchemy import or_

from app.agent.attachments import require_upload_job_owner
from app.api import AppError
from app.models import Job


def private_jobs():
    return Job.query.filter(or_(Job.strategy == "agent_upload",
        Job.config["agent_story_preview"]["run_id"].as_string().is_not(None),
        Job.config["agent_story_production"]["run_id"].as_string().is_not(None),
        Job.config["agent_transform"].as_string().is_not(None))).all()


def hidden_job_ids(owner_id):
    hidden = []
    for job in private_jobs():
        try:
            require_upload_job_owner(job, owner_id)
        except AppError:
            hidden.append(job.id)
    return hidden


def protected_prompt_templates():
    # Historical template-level sync can contain more than one user's input.
    return {"agent_workspace"} | {job.template.template_id for job in private_jobs() if job.template}


def visible_prompt_assets(assets, owner_id):
    hidden = {job.job_id for job in Job.query.filter(Job.id.in_(hidden_job_ids(owner_id))).all()}
    protected = protected_prompt_templates()
    return [asset for asset in assets if asset.get("job_id") not in hidden
        and (asset.get("job_id") or asset.get("template_id") not in protected)]
