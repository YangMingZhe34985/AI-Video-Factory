"""Deterministic structural delivery checks; never a semantic quality claim."""
from pydantic import BaseModel, ConfigDict, Field
from app.api import AppError
from app.agent.delivery_policy import approved_sources, require_delivery_authorization, resolve_delivery_artifact, resolve_source
from app.services.media_probe_service import MediaProbeService
from app.tools.permissions import PRODUCTION, SYSTEM, WRITE
from app.tools.spec import ToolSpec

class QcVideoInput(BaseModel):
    model_config = ConfigDict(extra="forbid")
    plan_version: int = Field(ge=1, strict=True)
    artifact_id: str = Field(min_length=1, max_length=80)
    video_artifact_ids: list[str] = Field(min_length=1, max_length=120)

class QcCheck(BaseModel):
    code: str
    passed: bool
    summary: str

class QcVideoOutput(BaseModel):
    passed: bool
    checks: list[QcCheck]
    warnings: list[str]


def within_duration(actual, expected):
    return abs(actual - expected) <= max(.5, expected * .02)


def validate_sources(data, ctx):
    owner, version = require_delivery_authorization(ctx, data.plan_version)
    sources = approved_sources(owner, version)
    if data.video_artifact_ids != [item.artifact_id for _shot, _task, item in sources]:
        raise AppError("INVALID_REFERENCE", "QC sources differ from the approved shot order", 422)
    master = resolve_delivery_artifact(owner, version, data.artifact_id)
    return owner, version, sources, master


def run(data, ctx):
    owner, version, sources, master = validate_sources(data, ctx)
    checks, warnings = [], []
    first_media = None
    def check(code, passed, summary):
        checks.append({"code": code, "passed": bool(passed), "summary": summary})
    check("SHOT_SEQUENCE", len(sources) == len(version.plan["shots"]), "批准镜头齐全且顺序一致")
    for shot, _task, artifact in sources:
        try:
            media = MediaProbeService.probe(resolve_source(artifact), decode=True, mock_duration_sec=shot["duration_sec"])
            if first_media is None:
                first_media = media
            check("SOURCE_DECODE:" + shot["shot_id"], media["decoded"] or media["mock"], "源镜头可读取：" + shot["shot_id"])
            check("SOURCE_DURATION:" + shot["shot_id"], within_duration(media["duration_sec"], shot["duration_sec"]), "源镜头时长符合已批准分镜：" + shot["shot_id"])
            if media["mock"]:
                warnings.append("Mock 源镜头为示意数据，质检不代表真实画质。")
        except AppError as error:
            check("SOURCE_DECODE:" + shot["shot_id"], False, "源镜头不可用：" + error.code)
    # The target comes from the approved first source, not the output's own
    # reported dimensions. Exact Mock sentinels materialize at 320x180/25 fps.
    expected_width = expected_height = expected_fps = None
    normalize = owner.snapshot["delivery"]["composition"]["composition"]["mode"] == "normalized"
    if first_media:
        expected_width = 320 if first_media["mock"] else first_media["width"] + (first_media["width"] % 2 if normalize else 0)
        expected_height = 180 if first_media["mock"] else first_media["height"] + (first_media["height"] % 2 if normalize else 0)
        expected_fps = 25.0 if first_media["mock"] else first_media.get("fps")
    try:
        media = MediaProbeService.probe(resolve_source(master), decode=True)
        check("MASTER_DECODE", media["decoded"] and not media["mock"], "主片完整解码通过")
        expected = sum(shot["duration_sec"] for shot, _task, _artifact in sources)
        check("TOTAL_DURATION", within_duration(media["duration_sec"], expected), "主片时长与批准镜头总和一致")
        check("OUTPUT_DIMENSIONS", (media["width"], media["height"]) == (expected_width, expected_height), "主片画幅符合拼接规格")
        check("OUTPUT_FRAME_RATE", media["fps"] is not None and expected_fps is not None and abs(media["fps"] - expected_fps) <= .05, "主片帧率符合拼接规格")
        check("OUTPUT_STREAM_LAYOUT", media["stream_count"] == 1 + int(media["has_audio"]), "主片包含一个视频流及可选音频流")
    except AppError as error:
        check("MASTER_DECODE", False, "主片不可用：" + error.code)
    compressed_id = ((owner.snapshot or {}).get("delivery", {}).get("composition") or {}).get("compressed_artifact_id")
    if compressed_id:
        try:
            compressed = resolve_delivery_artifact(owner, version, compressed_id, kind="compressed")
            proxy = MediaProbeService.probe(resolve_source(compressed), decode=True)
            expected = sum(shot["duration_sec"] for shot, _task, _artifact in sources)
            check("COMPRESSED_DECODE", proxy["decoded"] and not proxy["mock"], "压缩副本完整解码通过")
            check("COMPRESSED_DURATION", within_duration(proxy["duration_sec"], expected), "压缩副本时长与批准分镜一致")
            check("COMPRESSED_DIMENSIONS", (proxy["width"], proxy["height"]) == (expected_width, expected_height), "压缩副本画幅与主片一致")
            check("COMPRESSED_FRAME_RATE", proxy["fps"] is not None and expected_fps is not None and abs(proxy["fps"] - expected_fps) <= .05, "压缩副本帧率与主片一致")
        except AppError as error:
            check("COMPRESSED_DECODE", False, "压缩副本不可用：" + error.code)
    return {"passed": all(item["passed"] for item in checks), "checks": checks, "warnings": list(dict.fromkeys(warnings))}

SPEC = ToolSpec(name="qc_video", description="Verify approved shots and final video structure without model calls.",
    input_model=QcVideoInput, output_model=QcVideoOutput, handler=run, permission=WRITE,
    allowed_roles=frozenset({PRODUCTION, SYSTEM}), requires_approval=True, timeout_sec=1200, max_retries=0)
