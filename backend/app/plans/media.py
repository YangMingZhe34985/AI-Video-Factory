"""Plan-only media handlers over the existing local services and Job engine."""
from copy import deepcopy
from hashlib import sha256
import json
import zipfile

from app.api import AppError
from app.extensions import db
from app.models import Artifact, Job, ToolInvocation
from app.plans import policy
from app.plans.execution import artifact_for_run, fingerprint
from app.services.artifact_service import ArtifactService
from app.services.file_fingerprint import cached_digest
from app.services.job_service import JobService
from app.services.media_probe_service import MediaProbeService
from app.services.storage_service import StorageService
from app.services.video_composition_service import VideoCompositionService
from app.services.video_media_service import VideoMediaService
from app.tools import job_backed
from app.utils.time_utils import utc_now


def _source(run, artifact_id, kind="video"):
    artifact = artifact_for_run(run, artifact_id, kind)
    return artifact, StorageService.resolve(artifact.file_path)


def _duration(artifact, path, *, decode=False):
    metadata = artifact.meta or {}
    hint = metadata.get("plan_output", {}).get("duration_sec")
    if hint is None:
        media = metadata.get("media") or {}
        hint = media.get("duration_sec", media.get("duration"))
    return MediaProbeService.probe(path, decode=decode, mock_duration_sec=hint)


def _target(ctx, suffix):
    folder = StorageService.root() / "agent" / "plans" / sha256(ctx.budget_scope.encode()).hexdigest()
    folder.mkdir(parents=True, exist_ok=True)
    return folder / (ctx.invocation_id + suffix)


def _invocation(ctx):
    return ToolInvocation.query.filter_by(invocation_id=ctx.invocation_id, budget_scope=ctx.budget_scope).one()


def _local_job(ctx):
    invocation = _invocation(ctx)
    if invocation.job is not None:
        return invocation.job
    job = Job.query.filter(Job.config["skill"]["invocation_id"].as_string() == ctx.invocation_id).first()
    if job is None:
        template = job_backed.ensure_agent_template()
        job = JobService.create_job({"template_id": template.template_id, "strategy": "skill:" + ctx.tool_name,
            **job_backed.node_selection([]), "job_config": {"agent_plan": policy.job_marker(ctx),
                "agent_output_policy": {"compress_output": False}, "skill": {"invocation_id": ctx.invocation_id,
                    "budget_scope": ctx.budget_scope, "tool_name": ctx.tool_name, "caller_role": ctx.role}}}, commit=False)
    invocation.job = job
    db.session.flush()
    return job


def _save(ctx, job, path, kind):
    artifact = Artifact.query.filter_by(job_id=job.id, artifact_type=kind).first()
    metadata = {"plan_media": {"invocation_id": ctx.invocation_id, "sha256": cached_digest(path)}}
    if artifact is None:
        artifact = ArtifactService.register_artifact(job, StorageService.relative_path(path), kind, metadata=metadata)
    else:
        artifact.file_path, artifact.size, artifact.meta = StorageService.relative_path(path), path.stat().st_size, metadata
    return artifact


def cached_output_is_valid(invocation):
    output = invocation.output_payload or {}
    ids = [output.get(key) for key in ("artifact_id", "compressed_artifact_id") if output.get(key)]
    if not ids:
        return False
    for artifact_id in ids:
        artifact = Artifact.query.filter_by(artifact_id=artifact_id, job_id=invocation.job_id).first()
        if not artifact:
            return False
        try:
            path = StorageService.resolve(artifact.file_path)
            if (not path.resolve().is_relative_to(StorageService.root()) or not path.is_file()
                    or (artifact.meta or {}).get("plan_media", {}).get("sha256") != cached_digest(path)):
                return False
        except (OSError, ValueError):
            return False
    return True


def _finish(ctx, output, job=None):
    invocation = _invocation(ctx)
    if job is not None:
        invocation.job, job.status = job, "success"
        policy.bind_job(ctx, job)
    invocation.output_payload = deepcopy(output)
    invocation.status, invocation.finished_at = "success", utc_now()
    db.session.commit()
    return output


def _replay(ctx):
    invocation = _invocation(ctx)
    if cached_output_is_valid(invocation):
        return deepcopy(invocation.output_payload)
    return None


def transform_video(data, ctx):
    from app.services.wan3_media_service import Wan3MediaService
    from app.tools.budget import estimate_model_cost
    from app.services.model_service import ModelService
    run, task, _version, _node = policy.task_context(ctx)
    resolved, seconds, audio = [], 0.0, 0.0
    kinds = {"reference_image": "image", "reference_video": "video", "reference_audio": "audio", "file": "document"}
    for reference in data.media:
        artifact, path = _source(run, reference.artifact_id, kinds[reference.type])
        kind = "file" if reference.type == "file" else kinds[reference.type]
        before = fingerprint(run, artifact.artifact_id)
        metadata = Wan3MediaService.inspect(path, kind)
        if before != fingerprint(run, artifact.artifact_id):
            raise AppError("PLAN_INPUT_CHANGED", "Transform input changed during inspection", 409)
        if kind == "video":
            seconds += metadata["duration_sec"]
        if kind == "audio":
            audio += metadata["duration_sec"]
        resolved.append({"type": reference.type, "url": str(path)})
    if seconds > float(task.state.get("input_video_seconds", 0)) + .000001 or seconds > 15 or audio > 15:
        raise AppError("PLAN_INPUT_CHANGED", "Actual reference duration exceeds the approved bound", 409)
    model = ModelService.get_model(data.model_id, require_enabled=True)
    if estimate_model_cost(model, data.params, input_video_seconds=seconds) > task.estimated_cost + .000001:
        raise AppError("MODEL_PRICE_CHANGED", "Actual transform estimate exceeds the approved cost", 409)
    logical = {"prompt": data.prompt, "media": resolved}
    job = job_backed.launch(ctx, ["submit_r2v_flash", "poll_r2v_flash"],
        initial_prompts={"r2v_flash": data.prompt}, job_config={"agent_plan_inputs": logical,
            "node_models": {"submit_r2v_flash": data.model_id},
            "node_model_params": {"submit_r2v_flash": data.params}})
    return job_backed.launch_output(job, ["artifact:r2v_flash_video"])


def retain_video_segment(data, ctx):
    run, _task, _version, _node = policy.task_context(ctx)
    replay = _replay(ctx)
    if replay:
        return replay
    artifact, source = _source(run, data.video_artifact_id)
    media = _duration(artifact, source)
    if data.source_end_sec > media["duration_sec"]:
        raise AppError("INVALID_SOURCE_RANGE", "Source time range exceeds the original video", 422)
    target = _target(ctx, ".mp4")
    duration = data.source_end_sec - data.source_start_sec
    if media.get("mock"):
        VideoCompositionService._materialize_mock(target, duration, "retained", 0)
    else:
        VideoMediaService.extract(source, target, data.source_start_sec, data.source_end_sec, frame=False)
    job = _local_job(ctx)
    result = _save(ctx, job, target, "retained_video")
    return _finish(ctx, {"artifact_id": result.artifact_id, "source_artifact_id": artifact.artifact_id,
        "duration_sec": duration, "job_id": job.job_id}, job)


def compose_video(data, ctx):
    run, _task, _version, _node = policy.task_context(ctx)
    replay = _replay(ctx)
    if replay:
        return replay
    sources = [_source(run, key) for key in data.video_artifact_ids]
    durations = [_duration(artifact, path)["duration_sec"] for artifact, path in sources]
    target = _target(ctx, ".mp4")
    result = VideoCompositionService.compose([path for _, path in sources], target, durations=durations,
        shot_ids=data.video_artifact_ids, compress_output=data.compress_output)
    compressed_path = result.pop("compressed_path")
    job = _local_job(ctx)
    master = _save(ctx, job, target, "composed_video")
    compressed = _save(ctx, job, StorageService.resolve(compressed_path), "composed_video_compressed") if compressed_path else None
    return _finish(ctx, {"job_id": job.job_id, "artifact_id": master.artifact_id,
        "compressed_artifact_id": compressed.artifact_id if compressed else None,
        "preview_url": f"/api/artifacts/{master.artifact_id}/preview",
        "download_url": f"/api/artifacts/{master.artifact_id}/download",
        "composition": {**result, "source_artifact_ids": data.video_artifact_ids}}, job)


def probe_media(data, ctx):
    run, _task, _version, _node = policy.task_context(ctx)
    artifact, path = _source(run, data.artifact_id)
    return _finish(ctx, {"artifact_id": artifact.artifact_id, "media": _duration(artifact, path, decode=True)})


def qc_video(data, ctx):
    from app.tools.specs.qc_video import within_duration
    run, _task, _version, _node = policy.task_context(ctx)
    checks, total, source_meta = [], 0.0, []
    for key in data.video_artifact_ids:
        artifact, path = _source(run, key)
        media = _duration(artifact, path, decode=True)
        expected = (artifact.meta or {}).get("plan_output", {}).get("duration_sec")
        expected = media["duration_sec"] if expected is None else float(expected)
        total += expected
        source_meta.append(media)
        checks.append({"code": "SOURCE_DECODE:" + key, "passed": True, "summary": "源片段可解码"})
        checks.append({"code": "SOURCE_DURATION:" + key,
            "passed": within_duration(media["duration_sec"], expected), "summary": "源片段时长符合批准计划"})
    artifact, path = _source(run, data.artifact_id)
    media = _duration(artifact, path, decode=True)
    checks += [{"code": "MASTER_DECODE", "passed": True, "summary": "主片可解码"},
        {"code": "TOTAL_DURATION", "passed": within_duration(media["duration_sec"], total), "summary": "主片时长与批准片段总和一致"},
        {"code": "AUDIO_PRESERVED", "passed": not any(item.get("has_audio") for item in source_meta) or bool(media.get("has_audio")),
         "summary": "源音轨保留"}]
    return _finish(ctx, {"passed": all(item["passed"] for item in checks), "checks": checks,
        "warnings": ["仅验证文件结构与时长，未验证审美、角色一致性或叙事质量。"]})


def _require_qc_inputs(run, qc):
    expected = (qc.state or {}).get("input_fingerprints", {})
    ids = set(qc.inputs["video_artifact_ids"]) | {qc.inputs["artifact_id"]}
    if set(expected) != ids or any(fingerprint(run, key, "video") != expected[key] for key in ids):
        raise AppError("PLAN_INPUT_CHANGED", "Quality-checked sources changed before packaging", 409)


def package_story(data, ctx):
    from app.plans.runtime import latest_tasks
    from app.tools.specs.package_story import _safe
    from app.tools.budget import BudgetGuard
    run, _task, version, _node = policy.task_context(ctx)
    tasks = latest_tasks(run, version)
    matches = [task for task in tasks.values() if task.status == "success" and task.state.get("tool") == "qc_video"
        and task.inputs.get("artifact_id") == data.artifact_id and task.output.get("passed") is True]
    if not matches:
        raise AppError("PLAN_QC_REQUIRED", "Packaging requires a successful quality check for this master", 409)
    qc = matches[-1]
    _require_qc_inputs(run, qc)
    replay = _replay(ctx)
    if replay:
        return replay
    master, path = _source(run, data.artifact_id)
    sources = [_source(run, key) for key in qc.inputs["video_artifact_ids"]]
    target = _target(ctx, ".zip")
    temporary = target.with_suffix(".partial.zip")
    manifest = {"schema_version": 3, "run_id": run.run_id, "plan_version": version.version,
        "master_artifact_id": master.artifact_id, "source_artifact_ids": qc.inputs["video_artifact_ids"],
        "retained_sources": [{"node_id": task.node_id, "source_task_id": task.state["source_task_id"],
            "source_plan_version": task.state["source_plan_version"], "source_node_id": task.state["source_node_id"],
            "artifact_ids": [key for key in task.artifact_ids if key in qc.inputs["video_artifact_ids"]],
            "continuity_risk_accepted": bool(task.state.get("continuity_risk_accepted"))}
            for task in tasks.values() if task.status == "success" and task.state.get("retained_by_only")
            and set(task.artifact_ids).intersection(qc.inputs["video_artifact_ids"])],
        "costs": {"estimated_spent_credits": BudgetGuard.spent(run.run_id), "delivery_credits": 0},
        "demo_prices": True}
    try:
        with zipfile.ZipFile(temporary, "w", compression=zipfile.ZIP_STORED) as archive:
            archive.write(path, "final/master.mp4")
            for index, (_artifact, source_path) in enumerate(sources):
                archive.write(source_path, f"sources/{index + 1:03d}{source_path.suffix.lower()}")
            if data.compressed_artifact_id:
                _compressed, compressed_path = _source(run, data.compressed_artifact_id)
                archive.write(compressed_path, "final/compressed.mp4")
            for name, payload in (("manifest", manifest), ("plan", version.plan), ("qc", qc.output)):
                archive.writestr(name + ".json", json.dumps(_safe(payload), ensure_ascii=False, allow_nan=False, indent=2))
        _require_qc_inputs(run, qc)
        temporary.replace(target)
    finally:
        temporary.unlink(missing_ok=True)
    job = _local_job(ctx)
    artifact = _save(ctx, job, target, "story_package")
    return _finish(ctx, {"artifact_id": artifact.artifact_id,
        "download_url": f"/api/artifacts/{artifact.artifact_id}/download", "file_name": "cinecrew-story.zip"}, job)
