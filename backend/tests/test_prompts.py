"""Prompt versioning, lineage, snapshots and user-edit protection."""

from app.models import JobEvent, JobPromptRef, PromptVersion


def _job_versions(job, prompt_type):
    return (
        PromptVersion.query.filter_by(job_id=job.id, prompt_type=prompt_type)
        .order_by(PromptVersion.id.asc())
        .all()
    )


def _active_job_prompt(job, prompt_type):
    return PromptVersion.query.filter_by(job_id=job.id, prompt_type=prompt_type, is_active=True).one()


def test_generated_prompts_have_lineage_snapshots_and_template_sync(app_ctx, h, source_video):
    job = h.run_full(h.make_job(source_video=source_video).job_id)

    t2v = _active_job_prompt(job, "t2v")
    assert t2v.source == "reverse_prompts"
    for prompt_type in ("first_frame_image", "i2v"):
        prompt = _active_job_prompt(job, prompt_type)
        assert prompt.source == "rewrite_prompts"
        assert prompt.parent_version == t2v.version

    snapshot_types = {ref.prompt_type for ref in JobPromptRef.query.filter_by(job_id=job.id)}
    assert {"video_understanding_system", "t2v", "prompt_rewrite_system", "first_frame_image", "i2v"} <= snapshot_types

    synced = PromptVersion.query.filter(
        PromptVersion.job_id.is_(None), PromptVersion.source == "synced_from_job"
    ).all()
    assert {"t2v", "first_frame_image", "i2v"} <= {prompt.prompt_type for prompt in synced}


def test_edit_and_rollback_append_new_versions(app_ctx, client, h, source_video):
    job = h.run_full(h.make_job(source_video=source_video).job_id)
    original = _active_job_prompt(job, "t2v")

    edited = client.post(
        f"/api/templates/default/prompts/t2v/versions/{original.version}/edit",
        json={"job_id": job.job_id, "content": "edited t2v prompt"},
    )
    assert edited.status_code == 201
    assert edited.json["data"]["source"] == "edit"

    rolled_back = client.post(
        f"/api/templates/default/prompts/t2v/versions/{original.version}/rollback",
        json={"job_id": job.job_id},
    )
    assert rolled_back.status_code == 201
    assert rolled_back.json["data"]["source"] == "rollback"

    versions = _job_versions(job, "t2v")
    assert [prompt.source for prompt in versions] == ["reverse_prompts", "edit", "rollback"]
    assert len({prompt.version for prompt in versions}) == 3
    active = _active_job_prompt(job, "t2v")
    assert active.content == original.content
    assert active.parent_version == original.version


def test_user_edit_is_preserved_when_generation_node_reruns(app_ctx, client, h, source_video):
    job = h.run_full(h.make_job(source_video=source_video).job_id)
    original = _active_job_prompt(job, "t2v")
    response = client.post(
        f"/api/templates/default/prompts/t2v/versions/{original.version}/edit",
        json={"job_id": job.job_id, "content": "hand tuned t2v prompt"},
    )
    assert response.status_code == 201

    job = h.run_from(job.job_id, "reverse_prompts", force=True)

    assert job.status == "success"
    assert _active_job_prompt(job, "t2v").content == "hand tuned t2v prompt"
    assert [prompt.source for prompt in _job_versions(job, "t2v")] == ["reverse_prompts", "edit"]
    assert JobEvent.query.filter_by(job_id=job.id, event_type="PROMPT_USER_EDIT_PRESERVED").count() >= 1
