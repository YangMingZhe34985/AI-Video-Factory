"""Durable, zero-model-cost delivery stages for an approved story plan."""
from copy import deepcopy
from flask import current_app
from app.api import AppError
from app.agent import plan_versions as versions
from app.extensions import db
from app.models import Artifact, ToolInvocation
from app.services.storage_service import StorageService
from app.skills.spec import ToolContext

DELIVERY_ACTIONS = {"start_delivery", "retry_delivery"}


def enabled():
    return bool(current_app.config.get("AGENT_STORY_V2_ENABLED") and current_app.config.get("AGENT_STORY_DELIVERY_ENABLED"))


def update(run, **values):
    snapshot = deepcopy(run.snapshot or {})
    snapshot["delivery"] = {**snapshot.get("delivery", {}), **values}
    run.snapshot = snapshot
    db.session.commit()
    return snapshot["delivery"]


def _ctx(run, version, key=None):
    return ToolContext(role="production", approved=True, budget_scope=run.run_id,
        budget_limit=run.request["budget_limit"], delivery_version=version, idempotency_key=key)


def _artifact(ref):
    if not ref:
        return None
    artifact = Artifact.query.filter_by(artifact_id=ref).first()
    if not artifact:
        return None
    try:
        path = StorageService.resolve(artifact.file_path)
        return artifact if path.resolve().is_relative_to(StorageService.root()) and path.is_file() and path.stat().st_size else None
    except (OSError, ValueError):
        return None


def _valid_outputs(run):
    from app.agent.delivery_policy import require_delivery_authorization, resolve_delivery_artifact
    from app.skills.tools.package_story import cached_output_is_valid
    delivery = (run.snapshot or {}).get("delivery", {})
    composition = delivery.get("composition") or {}
    result = {"master": None, "compressed": None, "package": None}
    try:
        _owner, version = require_delivery_authorization(_ctx(run, delivery.get("plan_version")))
    except (AppError, OSError, ValueError):
        return result
    for kind, field in (("master", "artifact_id"), ("compressed", "compressed_artifact_id")):
        try:
            result[kind] = resolve_delivery_artifact(run, version, composition.get(field), kind=kind)
        except (AppError, OSError, ValueError):
            pass
    package = _artifact((delivery.get("package") or {}).get("artifact_id"))
    if package:
        invocation = ToolInvocation.query.filter_by(invocation_id=(package.meta or {}).get("story_package", {}).get("invocation_id"),
            budget_scope=run.run_id, tool_name="package_story").first()
        if invocation and cached_output_is_valid(invocation):
            result["package"] = package
    return result


def _outputs_valid(run, outputs=None):
    delivery = (run.snapshot or {}).get("delivery", {})
    outputs = _valid_outputs(run) if outputs is None else outputs
    return bool((delivery.get("qc") or {}).get("passed") and outputs["master"] and outputs["package"]
                and (not delivery.get("compress_output") or outputs["compressed"]))


def validate_command(run, command):
    if not enabled():
        raise AppError("DELIVERY_DISABLED", "本地成片交付尚未开启。", 409)
    version = versions.require_current_version(run, command["plan_version"])
    if (run.snapshot or {}).get("production", {}).get("approved_version") != version.version:
        raise AppError("PLAN_VERSION_CONFLICT", "交付需要当前已批准的视频版本。", 409)
    action = command["action"]
    allowed = (action == "start_delivery" and run.status == "videos_approved") or (
        action == "retry_delivery" and (run.status == "delivery_attention" or (run.status == "success" and not _outputs_valid(run))))
    if not allowed:
        raise AppError("INVALID_AGENT_STATE", "当前状态不能开始或恢复交付。", 409)
    return 0.0


def begin_delivery(run, version, *, retry=False, target_attempt=None):
    from app.agent.delivery_policy import approved_sources, source_hashes, require_delivery_authorization
    if not enabled():
        raise AppError("DELIVERY_DISABLED", "本地成片交付尚未开启。", 409)
    delivery = deepcopy((run.snapshot or {}).get("delivery", {}))
    if delivery.get("authorized"):
        require_delivery_authorization(_ctx(run, version.version), version.version)
        if delivery["plan_version"] != version.version:
            raise AppError("PLAN_VERSION_CONFLICT", "交付版本已变化。", 409)
        if not retry:
            return "editing"
        # Keep approved bytes, successful stages and their provenance intact.
        update(run, attempt=target_attempt or delivery.get("attempt", 1) + 1, stage="pending", error=None)
        return "editing"
    sources = approved_sources(run, version)
    compressed = (run.snapshot or {}).get("request_spec", {}).get("constraints", {}).get("compress_output") is True
    payload = {"plan_version": version.version, "video_artifact_ids": [item.artifact_id for _s, _t, item in sources], "compress_output": compressed}
    update(run, authorized=True, plan_version=version.version, approved_version=version.version,
        source_artifact_ids=payload["video_artifact_ids"], source_sha256=source_hashes(sources),
        compress_output=compressed, inputs_hash=versions.inputs_hash(payload), attempt=1,
        stage="pending", error=None, tools={}, probes={}, composition=None, qc=None, package=None)
    return "editing"


def apply_command(run, command):
    key = command["request_key"]
    fingerprint = versions.inputs_hash({field: command[field] for field in ("action", "plan_version", "request_key")})
    row = versions._lock_run(run)
    snapshot = deepcopy(row.snapshot or {})
    receipts = snapshot.setdefault("delivery_action_receipts", {})
    receipt = receipts.get(key)
    if receipt and receipt["inputs_hash"] != fingerprint:
        raise AppError("IDEMPOTENCY_KEY_CONFLICT", "操作标识已用于其他交付内容。", 409)
    if receipt and receipt.get("result"):
        db.session.commit()
        return deepcopy(receipt["result"])
    if not receipt or not receipt.get("intent"):
        validate_command(row, command)
        intent = {"target_attempt": ((row.snapshot or {}).get("delivery", {}).get("attempt", 0) + 1)}
        receipts[key] = {**(receipt or {}), "inputs_hash": fingerprint, "status": "applying", "intent": intent}
        row.snapshot = snapshot
        db.session.commit()
    else:
        intent = receipt["intent"]
        db.session.commit()
    try:
        status = begin_delivery(row, versions.require_current_version(row, command["plan_version"]), retry=command["action"] == "retry_delivery",
            target_attempt=intent["target_attempt"])
    except AppError as error:
        update(row, stage="failed", error={"code": error.code, "message": error.message})
        status = "delivery_attention"
    result = {"status": status, "delivery_error": (row.snapshot or {}).get("delivery", {}).get("error")}
    snapshot = deepcopy(row.snapshot or {})
    snapshot.setdefault("delivery_action_receipts", {})[key] = {"inputs_hash": fingerprint, "status": "completed", "result": result}
    row.snapshot = snapshot
    db.session.commit()
    return result


def _invoke(run, registry, name, payload, slot):
    delivery = deepcopy(run.snapshot["delivery"])
    attempt = delivery.get("attempt", 1)
    key = f"{run.run_id}:delivery:{delivery['plan_version']}:{attempt}:{slot}"
    tools = deepcopy(delivery.get("tools", {}))
    tools[slot] = {"key": key, "tool": name, "input": deepcopy(payload)}
    update(run, tools=tools)
    result = registry.invoke(name, payload, _ctx(run, delivery["plan_version"], key))
    if result["status"] != "success" or not result.get("output"):
        raise AppError("DELIVERY_INCOMPLETE", "本地交付步骤尚未完成。", 409)
    tools[slot] = {**tools[slot], "invocation_id": result["invocation_id"]}
    update(run, tools=tools)
    return result["output"]


def tick(run, registry):
    from app.agent.delivery_policy import require_delivery_authorization, resolve_delivery_artifact
    delivery = deepcopy((run.snapshot or {}).get("delivery", {}))
    try:
        if not enabled():
            raise AppError("DELIVERY_DISABLED", "本地成片交付尚未开启。", 409)
        _owner, version = require_delivery_authorization(_ctx(run, delivery.get("plan_version")))
        stage = delivery.get("stage", "pending")
        if stage == "pending":
            probes = {}
            for artifact_id in delivery["source_artifact_ids"]:
                probes[artifact_id] = _invoke(run, registry, "probe_media", {"artifact_id": artifact_id}, "probe:" + artifact_id)
            composition = delivery.get("composition") or {}
            cached = False
            if composition.get("artifact_id"):
                try:
                    resolve_delivery_artifact(run, version, composition["artifact_id"])
                    if delivery.get("compress_output"):
                        resolve_delivery_artifact(run, version, composition["compressed_artifact_id"], kind="compressed")
                    cached = True
                except AppError:
                    pass
            update(run, probes=probes, stage="checking" if cached else "composing", error=None)
            return "editing"
        if stage == "composing":
            result = _invoke(run, registry, "compose_video", {"plan_version": version.version,
                "video_artifact_ids": delivery["source_artifact_ids"], "compress_output": delivery["compress_output"]}, "compose")
            update(run, composition=result, qc=None, package=None, stage="checking")
            return "editing"
        composition = delivery.get("composition") or {}
        if stage == "checking":
            result = _invoke(run, registry, "qc_video", {"plan_version": version.version,
                "artifact_id": composition["artifact_id"], "video_artifact_ids": delivery["source_artifact_ids"]}, "qc")
            update(run, qc=result)
            if not result["passed"]:
                raise AppError("DELIVERY_QC_FAILED", "成片未通过结构质检，请检查失败项目后恢复。", 409)
            update(run, stage="packaging")
            return "editing"
        if stage == "packaging":
            result = _invoke(run, registry, "package_story", {"plan_version": version.version,
                "artifact_id": composition["artifact_id"], "compressed_artifact_id": composition.get("compressed_artifact_id")}, "package")
            update(run, package=result, stage="complete", error=None)
            return "success"
        if stage == "complete" and _outputs_valid(run):
            return "success"
        raise AppError("DELIVERY_INCOMPLETE", "交付文件不完整，请恢复本地交付。", 409)
    except AppError as error:
        update(run, stage="failed", error={"code": error.code, "message": error.message})
    except Exception:
        db.session.rollback()
        current_app.logger.exception("Local delivery failed for run %s", run.run_id)
        update(run, stage="failed", error={"code": "DELIVERY_FAILED", "message": "本地交付步骤失败，可恢复；不会重新生成视频。"})
    return "delivery_attention"


def public_delivery(run):
    version = versions.current_version(run)
    if not version or not version.story_package:
        return None
    delivery = (run.snapshot or {}).get("delivery", {})
    composition = delivery.get("composition") or {}
    details = composition.get("composition") or {}
    outputs = _valid_outputs(run)
    def media_ref(kind):
        artifact = outputs[kind]
        if not artifact:
            return None
        return {"artifact_id": artifact.artifact_id, "preview_url": f"/api/artifacts/{artifact.artifact_id}/preview",
            "download_url": f"/api/artifacts/{artifact.artifact_id}/download", "file_name": artifact.file_name,
            **{key: details.get(key) for key in ("duration_sec", "width", "height", "fps")}, "composition_mode": details.get("mode")}
    package = delivery.get("package") or {}
    package_ref = deepcopy(package) if outputs["package"] else None
    return {"enabled": enabled(), "plan_version": version.version, "status": run.status,
        "stage": delivery.get("stage", "pending"), "error": delivery.get("error"), "cost_credits": 0,
        "can_start": enabled() and run.status == "videos_approved",
        "can_retry": enabled() and (run.status == "delivery_attention" or (run.status == "success" and not _outputs_valid(run, outputs))),
        "master": media_ref("master"), "compressed": media_ref("compressed"),
        "package": package_ref, "qc": delivery.get("qc"), "warnings": list(dict.fromkeys([
            *details.get("warnings", []), *(delivery.get("qc") or {}).get("warnings", []),
            *(["Mock 成片使用示意素材，不代表真实生成效果。"] if details.get("mock_materialized") else [])]))}
