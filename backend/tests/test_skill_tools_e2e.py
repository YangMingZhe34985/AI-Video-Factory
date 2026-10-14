"""From-scratch tool chain in mock mode, driven only through the registry."""

import zipfile

from app.models import Artifact, Job, PromptVersion, Template
from app.services.storage_service import StorageService
from app.skills import get_registry
from app.skills.job_backed import AGENT_TEMPLATE_ID
from app.skills.spec import ToolContext


def invoke(name, data, role, approved=False, **ctx):
    return get_registry().invoke(name, data, ToolContext(role=role, approved=approved, **ctx))


def finished_status(h, launch):
    h.wait_for_terminal(launch["output"]["job_id"])
    return invoke("get_task_status", {"invocation_id": launch["invocation_id"]}, role="director")["output"]


def test_analyze_rewrite_produce_package_chain(app_ctx, h, source_video):
    classic = h.make_job(source_video=source_video)
    source = Artifact.query.filter_by(job_id=classic.id, artifact_type="source_video").one()
    default_template = Template.query.filter_by(template_id="default").one()
    default_prompt_count = PromptVersion.query.filter_by(template_id=default_template.id).count()

    analysis = finished_status(
        h, invoke("analyze_video", {"source_artifact_id": source.artifact_id}, role="creative")
    )
    assert analysis["status"] == "success"
    assert analysis["prompts"]["t2v"]

    rewrite = finished_status(
        h, invoke("rewrite_prompt", {"t2v_prompt": analysis["prompts"]["t2v"]}, role="creative")
    )
    assert rewrite["status"] == "success"
    assert {"first_frame_image", "i2v"} <= set(rewrite["prompts"])

    shot = invoke(
        "produce_shot",
        {
            "shot_id": "opening",
            "first_frame_prompt": rewrite["prompts"]["first_frame_image"],
            "i2v_prompt": rewrite["prompts"]["i2v"],
        },
        role="production",
        approved=True,
        budget_scope="film-1",
    )
    assert shot["output"]["expected_outputs"] == ["artifact:first_frame_image", "artifact:i2v_video"]
    shot_status = finished_status(h, shot)
    assert shot_status["status"] == "success"
    assert shot_status["terminal"] is True
    assert {"first_frame_image", "i2v_video"} <= {item["artifact_type"] for item in shot_status["artifacts"]}
    assert shot_status["invocation"]["status"] == "success"

    package = invoke("package_project", {"job_ids": [shot["output"]["job_id"]]}, role="production")
    archive_artifact = Artifact.query.filter_by(
        artifact_id=package["output"]["packages"][0]["artifact_id"]
    ).one()
    with zipfile.ZipFile(StorageService.resolve(archive_artifact.file_path)) as archive:
        assert any(name.startswith("final/") and name.endswith(".mp4") for name in archive.namelist())

    # Skill jobs are tagged, isolated in the agent template, and never add
    # prompt versions to classic templates.
    shot_job = Job.query.filter_by(job_id=shot["output"]["job_id"]).one()
    assert shot_job.strategy == "skill:produce_shot"
    assert shot_job.template.template_id == AGENT_TEMPLATE_ID
    assert shot_job.config["skill"]["invocation_id"] == shot["invocation_id"]
    assert shot_job.config["skill"]["budget_scope"] == "film-1"
    assert PromptVersion.query.filter_by(template_id=default_template.id).count() == default_prompt_count


def test_rerun_node_regenerates_a_shot_video(app_ctx, h):
    shot = invoke(
        "produce_shot",
        {"shot_id": "s1", "first_frame_prompt": "a cat sits", "i2v_prompt": "the cat jumps"},
        role="production",
        approved=True,
    )
    job = h.wait_for_terminal(shot["output"]["job_id"])
    videos_before = Artifact.query.filter_by(job_id=job.id, artifact_type="i2v_video").count()

    rerun = invoke(
        "rerun_node",
        {"job_id": job.job_id, "node_key": "submit_i2v", "mode": "from"},
        role="production",
        approved=True,
        idempotency_key="rerun-s1-1",
    )
    report = finished_status(h, rerun)

    assert report["terminal"] is True
    assert report["invocation"]["status"] == "success"
    assert Artifact.query.filter_by(job_id=job.id, artifact_type="i2v_video").count() == videos_before + 1


def test_generate_video_modes_reuse_artifacts(app_ctx, h):
    image = finished_status(
        h, invoke("generate_image", {"prompt": "a red fox"}, role="production", approved=True)
    )
    frame_id = next(item["artifact_id"] for item in image["artifacts"] if item["artifact_type"] == "first_frame_image")

    i2v = finished_status(
        h,
        invoke(
            "generate_video",
            {"mode": "i2v", "prompt": "the fox runs", "first_frame_artifact_id": frame_id},
            role="production",
            approved=True,
        ),
    )
    r2v = finished_status(
        h,
        invoke(
            "generate_video",
            {"mode": "r2v", "prompt": "the fox runs", "reference_artifact_ids": [frame_id]},
            role="production",
            approved=True,
        ),
    )

    assert "i2v_video" in {item["artifact_type"] for item in i2v["artifacts"]}
    assert "r2v_flash_video" in {item["artifact_type"] for item in r2v["artifacts"]}
    copies = Artifact.query.filter_by(artifact_type="first_frame_image").all()
    assert any((item.meta or {}).get("source_artifact_id") == frame_id for item in copies)
