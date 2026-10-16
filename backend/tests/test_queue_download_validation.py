"""Validate actual image bytes locally; no image-generation API is called."""
from pathlib import Path
import struct
import zlib

import pytest
from PIL import UnidentifiedImageError

from app.extensions import db
from app.models import ApiTask, Artifact, JobNodeRun
from app.queue.download import download, valid_receipt
from app.queue.state import claim, enqueue
from app.services.storage_service import StorageService


def png_bytes():
    def chunk(kind, data):
        return struct.pack(">I", len(data)) + kind + data + struct.pack(">I", zlib.crc32(kind + data))
    return (b"\x89PNG\r\n\x1a\n" + chunk(b"IHDR", struct.pack(">IIBBBBB", 1, 1, 8, 2, 0, 0, 0))
            + chunk(b"IDAT", zlib.compress(b"\x00\x80\x40\x20")) + chunk(b"IEND", b""))


@pytest.mark.parametrize("valid", [True, False])
def test_download_checks_image_content_before_registering(app_ctx, h, valid):
    job = h.make_job(paths=())
    node = JobNodeRun(job_id=job.id, node_key="poll_first_frame_image", status="waiting")
    db.session.add(node)
    db.session.flush()
    task = ApiTask(job_id=job.id, node_run_id=node.id, branch_key="first_frame_image",
        model_id="wan2.6-image", adapter_name="mock_image", operation_key="validated-image",
        queue_generation=0, expected_artifact_path=f"jobs/{job.job_id}/validated/image.png",
        response_payload={"status": "success"}, queue_data={"generation": True, "download": {
            "node_run_id": node.id, "artifact_type": "first_frame_image", "prompt_version": None,
            "metadata": {}, "artifact_branch_key": "first_frame_image"}})
    db.session.add(task)
    db.session.flush()
    enqueue(task, "download")
    db.session.commit()
    token = claim(task.id, "download", task.queue_generation)
    class BytesAdapter:
        use_mock = False  # Exercise production verification with local fixture bytes.
        def download_outputs(self, response, output_dir):
            path = Path(response["expected_output_path"])
            path.write_bytes(png_bytes() if valid else b"not an image")
            return [str(path)]
    target = StorageService.resolve(task.expected_artifact_path)
    if valid:
        download(task.id, token, BytesAdapter())
        db.session.commit()
        assert Artifact.query.filter_by(api_task_id=task.id).count() == 1
        assert valid_receipt(target, target.with_suffix(".png.receipt.json"))
    else:
        with pytest.raises(UnidentifiedImageError):
            download(task.id, token, BytesAdapter())
        db.session.rollback()
        assert Artifact.query.filter_by(api_task_id=task.id).count() == 0
        assert not target.exists()
