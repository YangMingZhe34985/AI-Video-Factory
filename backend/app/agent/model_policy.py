"""Server-owned video model constraints shared by every generation capability.

v1 preserves its original-request extraction. v2 consumes validated RequestSpec
constraints, never reinterpreting the text with legacy regular expressions.
"""

import re
import unicodedata

from flask import current_app

from app.api import AppError
from app.models import AgentRun, ModelRegistry
from app.services.model_service import ModelService
from app.services.workflow_service import WorkflowService

VIDEO_MODES = {
    "t2v": ("text_to_video", "submit_t2v", "DEFAULT_T2V_MODEL"),
    "i2v": ("image_to_video", "submit_i2v", "DEFAULT_I2V_MODEL"),
    "r2v": ("reference_to_video", "submit_r2v_flash", "DEFAULT_R2V_FLASH_MODEL"),
}
BASE_VIDEO_MODES = dict(VIDEO_MODES)
TRANSFORM_MODES = {"omni_reference", "video_edit", "video_extend"}
VIDEO_MODES.update({mode: ("reference_to_video", "submit_r2v_flash", "DEFAULT_R2V_FLASH_MODEL")
                    for mode in TRANSFORM_MODES})
VIDEO_TASKS = {item[0] for item in VIDEO_MODES.values()}
_REQUEST = re.compile(r"使用|采用|选用|指定|选择|限定|只用|必须|要求|想用|用|\b(?:use|using|with|choose|only|prefer|require|model|avoid|exclude)\b", re.I)
_NEGATIVE = re.compile(r"(?:不(?:要|想|能|应|允许|需要)?(?:使用|采用|选用|用)|别用|避免|排除|\b(?:not|don['’]t)(?:\s+(?:use|using|choose))?\b|\b(?:avoid|exclude)\b)", re.I)


def _normal(value):
    return re.sub(r"[\s_-]+", "", unicodedata.normalize("NFKC", value).casefold())


def _family(model):
    return ModelService.model_family(model)


def _selector(value):
    return re.sub(r"\s*(?:系列|模型|\bseries\b|\bfamily\b|\bmodel\b)\s*$", "", value, flags=re.I).strip()


def _matches_family(model, family):
    model, prefix = _normal(_family(model)), _normal(family)
    # wan2.7 must never match wan2.70; an unversioned family such as wan
    # can match wan2.7, and happyhorse can match happyhorse-1.0.
    return model == prefix or (model.startswith(prefix) and prefix[-1:].isalpha())


def _alias_pattern(value):
    return r"[\s_-]*".join(re.escape(part) for part in re.split(r"[\s_-]+", value))


def _mentions(goal, models):
    goal = unicodedata.normalize("NFKC", goal)
    non_video_ids = {model.model_id for model in ModelRegistry.query.all()
                     if not any(ModelService.supports_task_type(model, task) for task in VIDEO_TASKS)}
    aliases = {value for model in models for value in (
        model.model_id, model.display_name, _family(model),
        re.match(r"[A-Za-z]+", model.model_id).group(0) if re.match(r"[A-Za-z]+", model.model_id) else model.model_id,
    )}
    # Recognize familiar names even if that model/version is not registered.
    patterns = [r"wan[\s_-]*\d+(?:\.\d+)*(?:[-_][a-z0-9.]+)*(?:\s+(?:t2v|i2v|r2v))?",
                r"happy[\s_-]*horse(?:[\s_-]+\d+(?:\.\d+)*)?(?:[-_][a-z0-9.]+)*(?:\s+(?:t2v|i2v|r2v))?"]
    patterns += [_alias_pattern(alias) for alias in sorted(aliases, key=len, reverse=True)]
    patterns += [r"[a-z][a-z0-9]*(?:[-_.][a-z0-9]+)*[-_](?:t2v|i2v|r2v)(?:[-_][a-z0-9]+)*"]
    pattern = re.compile(r"(?<![a-z0-9])(?:" + "|".join(patterns) + r")(?![a-z0-9]|[.][a-z0-9]|[-_][a-z0-9])", re.I)
    positive, negative = [], []
    for match in pattern.finditer(goal):
        if ModelService.canonical_model_id(match.group()) in non_video_ids:
            continue
        # A mention in the scene/story is not necessarily a model request.
        prefix = re.split(r"[,，。;；!?！？\n]", goal[:match.start()])[-1][-100:]
        suffix = goal[match.end():match.end() + 24]
        if not (_REQUEST.search(prefix) or re.match(r"\s*(?:系列|模型|family|series|model)", suffix, re.I)
                or goal.strip() == match.group()):
            continue
        negative_cues, request_cues = list(_NEGATIVE.finditer(prefix)), list(_REQUEST.finditer(prefix))
        negated = bool(negative_cues) and (not request_cues or negative_cues[-1].end() >= request_cues[-1].end())
        target = negative if negated else positive
        target.append(match.group())
    # Unknown plain names in an explicit "use X model" request must fail
    # visibly instead of being mistaken for no preference.
    unknown = re.compile(
        r"(?:使用|采用|指定|选用|\buse\s+|\busing\s+|\bchoose\s+|\bprefer\s+)\s*"
        r"([a-z][a-z0-9._-]*)\s*(?=系列|(?:视频(?:生成)?)?模型|(?:video\s+)?model\b|family\b|series\b)", re.I)
    for match in unknown.finditer(goal):
        if not any(_normal(match.group(1)) == _normal(value) for value in positive + negative):
            if ModelService.canonical_model_id(match.group(1)) in non_video_ids:
                continue
            prefix = goal[max(0, match.start() - 8):match.start()]
            (negative if re.search(r"不|别|避免", prefix) else positive).append(match.group(1))
    return list(dict.fromkeys(positive)), list(dict.fromkeys(negative))


def _matching_ids(value, models):
    for candidate in (value.strip(), _selector(value)):
        canonical = ModelService.canonical_model_id(candidate)
        exact = [model.model_id for model in models if model.model_id == canonical
                 or _normal(candidate) in {_normal(model.model_id), _normal(model.display_name)}]
        if exact:
            return set(exact)
    return {model.model_id for model in models if _matches_family(model, _selector(value))}


def build_policy(goal: str, preference: str | None = None) -> dict:
    models = [model for model in ModelRegistry.query.all()
              if any(ModelService.supports_task_type(model, task) for task in VIDEO_TASKS)]
    required, excluded = _mentions(goal, models)
    if preference:
        required.append(preference)
    defaults = {}
    for mode, (_task, node, config_key) in VIDEO_MODES.items():
        config = WorkflowService.get_node(node).config or {}
        defaults[mode] = ModelService.canonical_model_id(config.get("model_id") or current_app.config[config_key])
    policy = {"source": "user" if required or excluded else "server_default",
              "requested": list(dict.fromkeys(required)), "excluded": excluded,
              "defaults": defaults, "allowed_model_ids": []}
    if policy["source"] == "server_default":
        return policy
    allowed = {model.model_id for model in models if model.enabled}
    for selector in policy["requested"]:
        matching = _matching_ids(selector, models)
        if not matching:
            raise AppError("MODEL_PREFERENCE_UNAVAILABLE", f"未找到视频模型或系列：{selector}。请修改模型要求或先在服务器注册模型。", 422)
        allowed &= matching
    for selector in excluded:
        allowed -= _matching_ids(selector, models)
    if not allowed:
        raise AppError("MODEL_PREFERENCE_UNAVAILABLE", "模型要求互相冲突，或匹配的视频模型均未启用；请修改要求。", 422)
    policy["allowed_model_ids"] = sorted(allowed)
    return policy


def request_policy(request: dict, request_spec: dict | None = None) -> dict | None:
    if request.get("schema_version", 1) == 2:
        if request_spec is None:
            return None  # Understanding must finish before generation model selection.
        from app.agent.model_selection import video_policy_for_request
        return video_policy_for_request(request_spec)
    return request.get("video_model_policy") or build_policy(request["goal"], request.get("video_model_preference"))


def scope_policy(scope: str) -> dict | None:
    row = AgentRun.query.filter_by(run_id=scope).first()
    if row is None:
        return None
    if row.request.get("schema_version", 1) == 2:
        snapshot = row.snapshot or {}
        return snapshot.get("video_model_policy") or request_policy(row.request, snapshot.get("request_spec"))
    return request_policy(row.request)


def candidates(policy: dict, mode: str):
    task_type = VIDEO_MODES[mode][0]
    ids = policy["allowed_model_ids"] if policy["source"] == "user" else [policy["defaults"][mode]]
    return [model for model in ModelRegistry.query.filter(ModelRegistry.model_id.in_(ids),
                                      ModelRegistry.enabled.is_(True)).order_by(ModelRegistry.model_id)
            if ModelService.supports_task_type(model, task_type)
            and (mode not in TRANSFORM_MODES or mode in (model.capabilities or {}).get("modes", []))]


def select_video_model(policy: dict, mode: str, requested: str | None = None):
    eligible = {model.model_id: model for model in candidates(policy, mode)}
    if not eligible:
        raise AppError("MODEL_CAPABILITY_UNAVAILABLE", f"模型要求没有已启用的 {mode.upper()} 视频模型；不能改用其他系列。", 422)
    if requested:
        requested = ModelService.canonical_model_id(requested)
        if requested not in eligible:
            raise AppError("MODEL_PREFERENCE_VIOLATION", f"视频模型 {requested} 不符合用户要求或服务器默认策略。", 422,
                           payload={"requested": policy["requested"], "allowed_model_ids": sorted(eligible)})
        return eligible[requested]
    return eligible.get(policy["defaults"][mode]) or eligible[sorted(eligible)[0]]


def validate_job_policy(job, policy=None):
    if (job.config or {}).get("agent_transform"):
        from app.agent.transform_policy import validate_job
        validate_job(job)
        return
    if (job.config or {}).get("agent_story_production"):
        from app.agent.production_policy import validate_job
        validate_job(job)
        return
    enabled = set((job.node_overrides or {}).get("enabled_nodes") or [])
    if not any(node in enabled for _task, node, _default in BASE_VIDEO_MODES.values()):
        return
    config = job.config or {}
    scope = (config.get("skill") or {}).get("budget_scope")
    policy = policy or (scope_policy(scope) if scope else None) or config.get("video_model_policy")
    if not policy:
        return
    for mode, (_task, node, _default) in BASE_VIDEO_MODES.items():
        if node in enabled:
            model_id = (config.get("node_models") or {}).get(node)
            if not model_id:
                raise AppError("MODEL_PREFERENCE_VIOLATION", f"Agent Job 的 {node} 尚未固定视频模型。", 422)
            select_video_model(policy, mode, model_id)
