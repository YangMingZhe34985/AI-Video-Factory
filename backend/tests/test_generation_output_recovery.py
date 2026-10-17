"""Multi-image download retries preserve completed files and never submit again."""
from pathlib import Path

import pytest

from app.adapters.dashscope_common import DashScopeGenerationAdapter
from app.adapters.mock import MockImageAdapter
from app.api import AppError
from app.extensions import db
from app.models import ApiTask, Artifact, JobNodeRun
from app.queue.download import download
from app.queue.state import claim, enqueue
from app.services.node_runner import NodeRunner
from app.services.storage_service import StorageService


@pytest.mark.parametrize("mq", [False, True])
def test_partial_download_retries_only_missing_images(app_ctx, h, mq):
    job = h.make_job(paths=())
    node = JobNodeRun(job_id=job.id, node_key="poll_first_frame_image", status="waiting")
    db.session.add(node)
    db.session.flush()
    task = ApiTask(job_id=job.id, node_run_id=node.id, branch_key="first_frame_image",
        model_id="wan2.6-image", adapter_name="mock_image", operation_key="three-images" if mq else None,
        expected_artifact_path=f"jobs/{job.job_id}/multi/image.png", request_payload={"parameters": {"n": 3}},
        response_payload={"status": "success", "output_kind": "image"}, queue_generation=0,
        queue_data={"params": {"n": 3}, "generation": True, "download": {
            "node_run_id": node.id, "artifact_type": "first_frame_image", "prompt_version": None,
            "metadata": {}, "artifact_branch_key": "first_frame_image"}})
    db.session.add(task)
    db.session.commit()
    calls = []

    class InterruptedAdapter(MockImageAdapter):
        fail_once = True

        def download_outputs(self, response, output_dir):
            name = Path(response["expected_output_path"]).name
            calls.append(name)
            if name == "image_002.png" and self.fail_once:
                self.fail_once = False
                raise OSError("injected image 2 download failure")
            return super().download_outputs(response, output_dir)

    adapter = InterruptedAdapter()

    def complete():
        if mq:
            enqueue(task, "download")
            db.session.commit()
            token = claim(task.id, "download", task.queue_generation)
            download(task.id, token, adapter)
        else:
            NodeRunner()._complete_task_from_adapter(job, node, task, adapter, task.response_payload, "first_frame_image")
        db.session.commit()

    with pytest.raises(OSError, match="image 2"):
        complete()
    db.session.rollback()
    assert StorageService.resolve(task.expected_artifact_path).is_file()
    complete()
    artifacts = Artifact.query.filter_by(api_task_id=task.id, artifact_type="first_frame_image").all()
    assert len(artifacts) == 3
    assert calls == ["image.png", "image_002.png", "image_002.png", "image_003.png"]
    assert [item.meta["output_index"] for item in artifacts] == [0, 1, 2]
    if not mq:
        complete()
        assert Artifact.query.filter_by(api_task_id=task.id, artifact_type="first_frame_image").count() == 3
        assert len(calls) == 4
        # An explicitly resubmitted provider task may reuse the classic filename;
        # it must download the new result instead of trusting the previous task's receipt.
        task.api_task_id = "new-provider-operation"
        db.session.commit()
        complete()
        assert len(calls) == 7
    else:
        assert task.queue_phase == "done"


def test_synchronous_result_preserves_all_urls_without_polling(app_ctx, h):
    task = ApiTask(response_payload={"status": "success", "synchronous": True,
                                    "result_urls": ["https://fixture/1", "https://fixture/2"]})
    class NoPolling:
        def poll(self, _task_id):
            pytest.fail("Completed synchronous response must be reused")
    assert NodeRunner()._poll_until_complete(NoPolling(), task)["result_urls"] == ["https://fixture/1", "https://fixture/2"]
    assert DashScopeGenerationAdapter._extract_image_urls({"output": {"choices": [{"message": {"content": [
        {"image": "https://fixture/1"}, {"image": "https://fixture/2"}]}}]}}) == ["https://fixture/1", "https://fixture/2"]


def test_missing_provider_candidate_is_a_failure_not_silent_success(app_ctx):
    from app.services.generation_outputs import output_slots
    task = ApiTask(expected_artifact_path="image.png", request_payload={"parameters": {"n": 3}})
    with pytest.raises(AppError, match="Expected 3 images"):
        output_slots(task, {"result_url": "https://fixture/1"}, "first_frame_image")
