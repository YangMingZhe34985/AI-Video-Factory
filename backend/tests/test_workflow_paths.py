"""Classic DAG paths run end-to-end in mock mode."""

import io
import json

import pytest
from werkzeug.datastructures import FileStorage

from app.api import AppError
from app.models import ApiTask, Artifact
from app.services.job_service import JobService
from app.services.storage_service import MOCK_PNG_BYTES, StorageService


def _executed(h, job) -> dict[str, str]:
    return {key: status for key, status in h.latest_node_states(job).items() if status != "skipped"}


def test_main_i2v_path(app_ctx, h, source_video):
    job = h.run_full(h.make_job(source_video=source_video).job_id)

    assert job.status == "success"
    assert _executed(h, job) == {
        "reverse_prompts": "success",
        "rewrite_prompts": "success",
        "submit_first_frame_image": "success",
        "poll_first_frame_image": "success",
        "submit_i2v": "success",
        "poll_i2v": "success",
        "export_manifest": "success",
    }
    types = set(h.artifact_types(job))
    assert {"source_video", "first_frame_image", "i2v_video", "manifest", "prompt_markdown"} <= types

    video = Artifact.query.filter_by(job_id=job.id, artifact_type="i2v_video").one()
    first_frame = Artifact.query.filter_by(job_id=job.id, artifact_type="first_frame_image").one()
    # The output path is anchored to both the prompt version and the input frame.
    assert f"_img_{first_frame.artifact_id}/" in video.file_path
    assert video.prompt_version


def test_manifest_is_written(app_ctx, h, source_video):
    job = h.run_full(h.make_job(source_video=source_video).job_id)

    manifest = Artifact.query.filter_by(job_id=job.id, artifact_type="manifest").one()
    data = json.loads(StorageService.resolve(manifest.file_path).read_text(encoding="utf-8"))
    assert data["job"]["job_id"] == job.job_id
    assert any(item["artifact_type"] == "i2v_video" for item in data["artifacts"])


def test_t2v_path(app_ctx, h, source_video):
    job = h.make_job(source_video=source_video, paths=("t2v",), extra_nodes=("reverse_prompts",))
    job = h.run_full(job.job_id)

    assert job.status == "success"
    assert _executed(h, job) == {
        "reverse_prompts": "success",
        "submit_t2v": "success",
        "poll_t2v": "success",
        "export_manifest": "success",
    }
    assert "t2v_video" in h.artifact_types(job)


def test_r2v_flash_samples_persona_references(app_ctx, h, source_video):
    job = h.make_job(source_video=source_video, paths=("r2v_flash",), extra_nodes=("reverse_prompts",))
    job = h.run_full(job.job_id)

    assert job.status == "success"
    types = h.artifact_types(job)
    assert "r2v_flash_video" in types
    assert "reference_image" in types


def test_r2v_flash_uses_uploaded_references(app_ctx, h, source_video):
    files = [
        FileStorage(stream=io.BytesIO(MOCK_PNG_BYTES), filename=f"ref{index}.png", content_type="image/png")
        for index in range(2)
    ]
    payload = {
        "template_id": "default",
        "source_video_path": str(source_video),
        **h.node_selection("r2v_flash", extra=("reverse_prompts",)),
    }
    job = JobService.create_job(payload, initial_files={"reference_images": files})
    job = h.run_full(job.job_id)

    assert job.status == "success"
    references = Artifact.query.filter_by(job_id=job.id, artifact_type="reference_image").all()
    assert len(references) == 2
    assert all((ref.meta or {}).get("source") == "upload" for ref in references)
    assert "r2v_flash_video" in h.artifact_types(job)


@pytest.mark.parametrize(
    ("mode", "shot_type", "sources_per_sample"),
    [("single_male", "single", 1), ("single_female", "single", 1), ("couple", "multi", 2)],
)
def test_i2i_test_path(app_ctx, h, source_video, mode, shot_type, sources_per_sample):
    job = h.make_job(
        source_video=source_video,
        paths=("core", "i2i_test"),
        job_config={"i2i_test": {"mode": mode, "test_count": 2}},
    )
    job = h.run_full(job.job_id)

    assert job.status == "success"
    types = h.artifact_types(job)
    assert types.count("i2i_test_source_image") == 2 * sources_per_sample
    assert types.count("i2i_test_first_frame_image") == 2
    assert types.count("i2i_test_video") == 2

    items = job.config["i2i_test_batch"]["items"]
    assert [(item["image_status"], item["i2v_status"]) for item in items] == [("success", "success")] * 2

    i2v_tasks = ApiTask.query.filter_by(job_id=job.id, branch_key="i2i_test_i2v").all()
    assert len(i2v_tasks) == 2
    assert all(f'"shot_type": "{shot_type}"' in json.dumps(task.request_payload) for task in i2v_tasks)


def test_missing_source_video_is_rejected(app_ctx, h):
    with pytest.raises(AppError) as exc:
        h.make_job()

    assert exc.value.code == "MISSING_INPUT"
    assert exc.value.status_code == 400
    assert [item["key"] for item in exc.value.payload["required_inputs"]] == ["source_video"]
