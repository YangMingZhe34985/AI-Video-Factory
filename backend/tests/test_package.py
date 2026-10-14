"""One-click job packaging."""

import zipfile

import pytest

from app.api import AppError
from app.services.job_package_service import JobPackageService
from app.services.storage_service import StorageService


def test_package_contains_final_assets_prompts_and_manifest(app_ctx, h, source_video):
    job = h.run_full(h.make_job(source_video=source_video).job_id)

    result = JobPackageService.create_or_refresh(job)

    assert result["package_status"] == "full"
    assert result["download_url"] == f"/api/artifacts/{result['artifact']['artifact_id']}/download"
    archive_path = StorageService.resolve(result["artifact"]["file_path"])
    with zipfile.ZipFile(archive_path) as archive:
        names = archive.namelist()
    assert any(name.startswith("final/") and name.endswith(".mp4") for name in names)
    assert any(name.startswith("assets/") and name.endswith(".png") for name in names)
    assert "prompts/prompts.json" in names
    assert "package_manifest.json" in names


def test_repackaging_reuses_the_package_artifact(app_ctx, h, source_video):
    job = h.run_full(h.make_job(source_video=source_video).job_id)

    first = JobPackageService.create_or_refresh(job)
    second = JobPackageService.create_or_refresh(job)

    assert first["artifact"]["artifact_id"] == second["artifact"]["artifact_id"]


def test_job_without_outputs_cannot_be_packaged(app_ctx, h, source_video):
    job = h.make_job(source_video=source_video)

    with pytest.raises(AppError) as exc:
        JobPackageService.create_or_refresh(job)

    assert exc.value.code == "NO_PACKABLE_CONTENT"
