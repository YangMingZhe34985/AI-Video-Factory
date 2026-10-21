"""Evaluation-only, locally rendered media adapters. No provider generation calls."""
from __future__ import annotations

import hashlib
import json
import os
from pathlib import Path
import threading
import time

from app.adapters.mock import MockImageAdapter, MockVideoAdapter
from app.api import AppError

MEDIA_NAMES = {
    "dashscope_image": "image", "dashscope_qwen_image": "image",
    "dashscope_multimodal_sync": "image", "dashscope_i2v": "video",
    "dashscope_t2v": "video", "dashscope_r2v_flash": "video", "dashscope_wan3": "video",
}
CONTROLLER = None


class MediaController:
    """Append-only local evidence and one explicit, one-shot provider failure."""
    def __init__(self, path):
        self.path = Path(path)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.lock = threading.RLock()
        self.failure = None
        self.submissions = {}
        self.label = "unlabeled"

    def event(self, kind, **data):
        item = {"at": time.time(), "pid": os.getpid(), "label": self.label, "kind": kind, **data}
        with self.lock, self.path.open("a", encoding="utf-8") as stream:
            stream.write(json.dumps(item, ensure_ascii=False, default=str) + "\n")
            stream.flush()
            os.fsync(stream.fileno())
        return item

    def rows(self):
        if not self.path.exists():
            return []
        return [json.loads(line) for line in self.path.read_text(encoding="utf-8").splitlines() if line.strip()]

    def arm(self, model_id, prompt, *, run_id, node_id):
        if self.failure:
            raise RuntimeError("An unconsumed failure is already armed")
        self.failure = {"model_id": model_id, "prompt": prompt, "run_id": run_id, "node_id": node_id}
        self.event("failure_armed", run_id=run_id, node_id=node_id, model_id=model_id)

    def before_submit(self, adapter, payload):
        prompt = (payload.get("inputs") or {}).get("prompt")
        digest = hashlib.sha256(json.dumps(payload, ensure_ascii=False, sort_keys=True).encode()).hexdigest()
        self.event("mock_submit", model_id=adapter.model_id, output_kind=adapter.output_kind, payload_sha256=digest)
        with self.lock:
            failure = self.failure
            if failure and adapter.output_kind == "video" and adapter.model_id == failure["model_id"] and prompt == failure["prompt"]:
                self.failure = None
                self.event("content_policy_injected", run_id=failure["run_id"], node_id=failure["node_id"], model_id=adapter.model_id)
                raise AppError("CONTENT_POLICY_VIOLATION", "V10b one-shot Mock content policy rejection", 422,
                               payload={"code": "DataInspectionFailed"})

    def summary(self):
        rows = self.rows()
        return {"mock_submissions": sum(row["kind"] == "mock_submit" for row in rows),
                "mock_images_written": sum(row["kind"] == "mock_image_written" for row in rows),
                "mock_videos_written": sum(row["kind"] == "mock_video_written" for row in rows),
                "content_policy_injections": sum(row["kind"] == "content_policy_injected" for row in rows),
                "real_media_adapter_attempts": sum(row["kind"] == "blocked_real_media" for row in rows),
                "actual_real_media_http_calls": 0,
                "evidence": "All original media submits blocked before dispatch; replacement adapters make no HTTP calls."}


class LocalMediaMixin:
    @property
    def use_mock(self):
        return True

    def submit(self, payload):
        CONTROLLER.before_submit(self, payload)
        result = super().submit(payload)
        self._submitted_payload = payload
        CONTROLLER.submissions[result["provider_task_id"]] = payload
        return result

    def _payload(self, response):
        task_id = response.get("provider_task_id")
        payload = CONTROLLER.submissions.get(task_id) or getattr(self, "_submitted_payload", None)
        if payload is None and task_id:
            from app.models import ApiTask
            task = ApiTask.query.filter_by(provider_task_id=task_id).one()
            payload = task.request_payload
        if not isinstance(payload, dict):
            raise RuntimeError("Mock media output requires the actual submitted payload")
        return payload


class LocalImageAdapter(LocalMediaMixin, MockImageAdapter):
    def download_outputs(self, response, output_dir):
        from PIL import Image, ImageDraw
        target = Path(response.get("expected_output_path") or Path(output_dir) / "image.png")
        target.parent.mkdir(parents=True, exist_ok=True)
        token = hashlib.sha256(str(target).encode()).digest()
        from mock_geometry import rendered_size
        width, height = rendered_size(self._payload(response), image=True)
        canvas = Image.new("RGB", (width, height), tuple(30 + value % 110 for value in token[:3]))
        draw = ImageDraw.Draw(canvas)
        draw.rectangle((16, 16, max(17, width - 17), max(17, height - 17)), outline="white", width=3)
        draw.text((35, 85), "CINECREW V10 MOCK\nLOCAL PLACEHOLDER\nNOT A GENERATED IMAGE", fill="white", spacing=15)
        draw.text((35, 240), target.name[:60], fill="white")
        canvas.save(target, format="PNG")
        CONTROLLER.event("mock_image_written", model_id=self.model_id, filename=target.name,
                         sha256=hashlib.sha256(target.read_bytes()).hexdigest())
        return [str(target)]


class LocalVideoAdapter(LocalMediaMixin, MockVideoAdapter):
    def download_outputs(self, response, output_dir):
        from app.services.video_composition_service import VideoCompositionService
        payload = self._payload(response)
        duration = (payload.get("parameters") or {}).get("duration")
        if isinstance(duration, bool) or not isinstance(duration, (int, float)) or not 0 < duration <= 600:
            raise RuntimeError("Mock video requires an explicitly approved duration; no default allowed")
        target = Path(response.get("expected_output_path") or Path(output_dir) / "video.mp4")
        target.parent.mkdir(parents=True, exist_ok=True)
        from mock_geometry import rendered_size
        VideoCompositionService._materialize_mock(target, duration, target.stem[:24], 0, size=rendered_size(payload))
        CONTROLLER.event("mock_video_written", model_id=self.model_id, filename=target.name,
                         duration_sec=duration, sha256=hashlib.sha256(target.read_bytes()).hexdigest())
        return [str(target)]


def install(path):
    """Keep global real chat mode; replace only generation adapters, locally."""
    global CONTROLLER
    from app import adapters
    if CONTROLLER is not None:
        if CONTROLLER.path.resolve() != Path(path).resolve():
            raise RuntimeError("Mock media already installed for another evidence path")
        return CONTROLLER
    CONTROLLER = MediaController(path)
    for name, kind in MEDIA_NAMES.items():
        original = adapters.ADAPTERS[name]
        def blocked(self, payload, _name=name):
            CONTROLLER.event("blocked_real_media", adapter=_name, model_id=self.model_id)
            raise RuntimeError("V10 real media generation is blocked before provider HTTP dispatch")
        original.submit = blocked
        adapters.ADAPTERS[name] = LocalImageAdapter if kind == "image" else LocalVideoAdapter
    CONTROLLER.event("installed", adapter_names=sorted(MEDIA_NAMES), actual_real_media_http_calls=0)
    return CONTROLLER
