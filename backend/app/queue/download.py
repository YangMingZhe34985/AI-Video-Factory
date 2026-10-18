"""Validated, task-scoped files survive a crash before database confirmation."""
import json
from pathlib import Path

from app.extensions import db
from app.models import ApiTask, Artifact, Job, JobNodeRun
from app.queue.state import fail, inactive_reason, owned
from app.services.storage_service import StorageService
from app.services.generation_outputs import digest, output_slots, valid_receipt
from app.utils.time_utils import utc_now


def _download_slot(task_id, token, adapter, relative, response, index):
    task = db.session.get(ApiTask, task_id)
    spec = task.queue_data["download"]
    target = StorageService.resolve(relative)
    receipt = target.with_suffix(target.suffix + ".receipt.json")
    target.parent.mkdir(parents=True, exist_ok=True)
    db.session.commit()
    temporary = target.parent / token / target.name
    artifact_metadata = {**(spec["metadata"] or {}), "output_index": index}
    original_file = None
    if not valid_receipt(target, receipt):
        temporary.parent.mkdir(parents=True, exist_ok=True)
        response["expected_output_path"] = str(temporary)
        outputs = adapter.download_outputs(response, str(temporary.parent))
        if not outputs:
            raise ValueError("Provider returned no downloadable output")
        downloaded = Path(outputs[0]).resolve()
        if not downloaded.is_relative_to(temporary.parent.resolve()) or not downloaded.stat().st_size:
            raise ValueError("Invalid or empty downloaded output")
        if not adapter.use_mock:
            if "video" in spec["artifact_type"]:
                from app.services.video_media_service import VideoMediaService
                VideoMediaService.inspect(downloaded)
            else:
                from PIL import Image
                with Image.open(downloaded) as image:
                    image.verify()
        if "video" in spec["artifact_type"]:
            from app.services.video_compression_service import VideoCompressionService
            selected, compression = VideoCompressionService.compress_for_job(downloaded, db.session.get(Job, task.job_id))
            if selected != downloaded:
                original_file = downloaded
                compression["original_file_path"] = StorageService.relative_path(target.with_name(target.stem + "_original" + target.suffix))
                compression["compressed_file_path"] = StorageService.relative_path(target)
            else:
                compression["original_file_path"] = StorageService.relative_path(target)
                compression["compressed_file_path"] = None
            downloaded = selected
            artifact_metadata["compression"] = compression
        checksum = digest(downloaded)
    else:
        downloaded = None
        checksum = digest(target)
        artifact_metadata = json.loads(receipt.read_text(encoding="utf-8")).get("metadata", artifact_metadata)
    # Fence BEFORE replacing the canonical file or registering an artifact.
    task = owned(task_id, token)
    if not task:
        db.session.rollback()
        return False
    reason = inactive_reason(task)
    if reason:
        fail(task, reason)
        task.status = "cancelled"
        return False
    artifact_metadata.update(run_id=task.request_payload.get("_run_id"),
                             run_mode=task.request_payload.get("_run_mode"))
    if downloaded:
        if original_file:
            original_file.replace(target.with_name(target.stem + "_original" + target.suffix))
        downloaded.replace(target)
        receipt_tmp = receipt.with_suffix(".tmp")
        receipt_tmp.write_text(json.dumps({"sha256": checksum, "metadata": artifact_metadata}), encoding="utf-8")
        receipt_tmp.replace(receipt)
    artifact = Artifact.query.filter_by(api_task_id=task.id, artifact_type=spec["artifact_type"],
                                       file_path=StorageService.relative_path(target)).first()
    if not artifact:
        from app.services.node_runner import NodeRunner
        NodeRunner()._register_task_output(
            db.session.get(Job, task.job_id), db.session.get(JobNodeRun, spec["node_run_id"]),
            task, {**task.response_payload, "status": "success"}, target,
            spec["artifact_type"], prompt_version=spec["prompt_version"],
            artifact_metadata={**artifact_metadata, "download_sha256": checksum},
            artifact_branch_key=spec["artifact_branch_key"],
        )
    # A partial set of image files is not a completed provider delivery.
    task.status = "generated"
    task.completed_at = None
    return True


def download(task_id, token, adapter):
    task = db.session.get(ApiTask, task_id)
    slots = output_slots(task, task.response_payload, task.queue_data["download"]["artifact_type"],
                         mock=adapter.use_mock)
    for index, (relative, response) in enumerate(slots):
        if not _download_slot(task_id, token, adapter, relative, response, index):
            return
    task = owned(task_id, token)
    if not task:
        db.session.rollback()
        return
    task.queue_phase = "done"
    task.status = "success"
    task.completed_at = utc_now()
    task.lease_token = None
    task.lease_until = None
    # Event acknowledgement is committed by process_event with this confirmation.
