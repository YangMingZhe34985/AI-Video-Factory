from copy import deepcopy
from math import gcd
import re

from app.api import AppError
from app.extensions import db
from app.models import ModelRegistry


VIDEO_DURATION_SCHEMA = {
    "duration": {
        "type": "integer",
        "label": "Duration (seconds)",
        "min": 1,
        "max": 30,
        "default": 5,
    },
    "resolution": {
        "type": "string",
        "label": "Resolution",
        "enum": ["480P", "720P", "1080P"],
        "default": "720P",
    },
    "prompt_extend": {
        "type": "boolean",
        "label": "Prompt Extend",
        "default": False,
    },
    "watermark": {
        "type": "boolean",
        "label": "Watermark",
        "default": False,
    },
}

HAPPYHORSE_I2V_PARAMETER_SCHEMA = {
    "duration": {
        "type": "integer",
        "label": "Duration (seconds)",
        "min": 3,
        "max": 15,
        "default": 5,
    },
    "resolution": {
        "type": "string",
        "label": "Resolution",
        "enum": ["720P", "1080P"],
        "default": "720P",
    },
    "watermark": {
        "type": "boolean",
        "label": "Watermark",
        "default": False,
    },
    "seed": {
        "type": "integer",
        "label": "Seed",
        "min": 0,
        "max": 2147483647,
    },
}

T2V_PARAMETER_SCHEMA = {
    **VIDEO_DURATION_SCHEMA,
    "ratio": {
        "type": "string",
        "label": "Aspect Ratio",
        "enum": ["9:16", "16:9", "1:1"],
        "default": "9:16",
    },
}

IMAGE_PARAMETER_SCHEMA = {
    "size": {
        "type": "string",
        "label": "Image Size",
        "enum": ["1024*1024", "1280*720", "720*1280", "1280*1280"],
        "default": "1280*1280",
    },
    "n": {"type": "integer", "label": "Count", "min": 1, "max": 4, "default": 1},
    "prompt_extend": {"type": "boolean", "label": "Prompt Extend", "default": True},
    "watermark": {"type": "boolean", "label": "Watermark", "default": False},
}

WAN27_IMAGE_PARAMETER_SCHEMA = {
    **IMAGE_PARAMETER_SCHEMA,
    "size": {
        "type": "string",
        "label": "Image Size",
        "enum": [
            "1024*1024",
            "1280*720",
            "720*1280",
            "1280*1280",
            "1920*1080",
            "1080*1920",
            "1440*1440",
        ],
        "default": "1280*1280",
    },
}

R2V_PARAMETER_SCHEMA = {
    "duration": {"type": "integer", "label": "Duration (seconds)", "min": 1, "max": 10, "default": 5},
    "size": {
        "type": "string",
        "label": "Video Size",
        "enum": ["720*1280", "1280*720", "960*960"],
        "default": "720*1280",
    },
    "audio": {"type": "boolean", "label": "Audio", "default": False},
    "shot_type": {
        "type": "string",
        "label": "Shot Type",
        "enum": ["single", "multi"],
        "default": "single",
    },
    "watermark": {"type": "boolean", "label": "Watermark", "default": False},
}

CHAT_PARAMETER_SCHEMA = {
    "temperature": {
        "type": "number",
        "label": "Temperature",
        "min": 0,
        "max": 2,
        "default": 0.2,
    }
}


GENERATION_TASK_MODES = {
    "text_to_image": {"t2i", "i2i"}, "text_to_video": {"t2v"},
    "image_to_video": {"i2v"}, "reference_to_video": {"r2v", "omni_reference", "video_edit", "video_extend"},
}
LEGACY_TASK_MODES = {**GENERATION_TASK_MODES, "reference_to_video": {"r2v"}, "text_to_image": {"t2i"}, "video_understanding": {"text", "image_understanding", "video_understanding"},
                     "text_to_text": {"text"}, "prompt_rewrite": {"text"}}

QWEN3_IMAGE_PARAMETER_SCHEMA = {
    "size": {"type": "string", "label": "Image Size", "format": "image_size",
             "min_pixels": 512 ** 2, "max_pixels": 2048 ** 2,
             "min_aspect_ratio": 1 / 8, "max_aspect_ratio": 8,
             "presets": ["1024*1024", "1536*864", "864*1536", "1024*768", "768*1024"], "default": "1024*1024"},
    "n": {"type": "integer", "label": "Count", "min": 1, "max": 6, "default": 1},
    "prompt_extend": {"type": "boolean", "label": "Prompt Extend", "default": True},
    "enable_thinking": {"type": "boolean", "label": "Enable Thinking", "default": False},
    "watermark": {"type": "boolean", "label": "Watermark", "default": False},
    "prompt_extend_mode": {"type": "string", "label": "Prompt Extend Mode", "enum": ["direct", "agent"], "default": "direct"},
    "negative_prompt": {"type": "string", "label": "Negative Prompt"},
    "seed": {"type": "integer", "label": "Seed", "min": 0, "max": 2147483647},
}
WAN3_VIDEO_PARAMETER_SCHEMA = {
    "duration": {"type": "integer", "label": "Duration (seconds)", "min": 2, "max": 30, "default": 5},
    "resolution": {"type": "string", "label": "Resolution", "enum": ["480P", "720P", "1080P"], "default": "720P"},
    "ratio": {"type": "string", "label": "Aspect Ratio", "enum": ["adaptive", "21:9", "16:9", "4:3", "1:1", "3:4", "9:16"], "default": "adaptive"},
    "audio": {"type": "boolean", "label": "Audio", "default": False},
    "prompt_extend": {"type": "boolean", "label": "Prompt Extend", "default": False},
    "watermark": {"type": "boolean", "label": "Watermark", "default": False},
    "seed": {"type": "integer", "label": "Seed", "min": -1, "max": 2147483647},
}


DEFAULT_MODELS = [
    {
        "model_id": "qwen3.7-plus",
        "display_name": "Qwen 3.7 Plus",
        "provider": "dashscope",
        "task_type": "video_understanding",
        "adapter_name": "qwen_chat",
        "default_params": {"temperature": 0.2, "fps": 2},
        "parameter_schema": {
            **CHAT_PARAMETER_SCHEMA,
            "fps": {"type": "integer", "label": "Video FPS Sampling", "min": 1, "max": 6, "default": 2},
        },
    },
    {
        "model_id": "qwen3.7-max",
        "display_name": "Qwen 3.7 Max",
        "provider": "dashscope",
        "task_type": "text_to_text",
        "adapter_name": "qwen_chat",
        "default_params": {"temperature": 0.2},
        "parameter_schema": CHAT_PARAMETER_SCHEMA,
    },
    {
        "model_id": "qwen3.6-plus",
        "display_name": "Qwen 3.6 Plus",
        "provider": "dashscope",
        "task_type": "video_understanding",
        "adapter_name": "qwen_chat",
        "default_params": {"temperature": 0.2, "fps": 2},
        "parameter_schema": {
            **CHAT_PARAMETER_SCHEMA,
            "fps": {"type": "integer", "label": "Video FPS Sampling", "min": 1, "max": 6, "default": 2},
        },
    },
    {
        "model_id": "qwen3.5-plus",
        "display_name": "Qwen 3.5 Plus",
        "provider": "dashscope",
        "task_type": "prompt_rewrite",
        "adapter_name": "qwen_chat",
        "default_params": {"temperature": 0.25},
        "parameter_schema": CHAT_PARAMETER_SCHEMA,
    },
    {
        "model_id": "deepseek-v4-flash",
        "display_name": "DeepSeek V4 Flash",
        "provider": "deepseek",
        "task_type": "text_to_text",
        "adapter_name": "qwen_chat",
        "default_params": {"temperature": 0.7},
        "parameter_schema": CHAT_PARAMETER_SCHEMA,
    },
    {
        "model_id": "glm-5.1",
        "display_name": "GLM 5.1",
        "provider": "dashscope",
        "task_type": "text_to_text",
        "adapter_name": "qwen_chat",
        "default_params": {"temperature": 0.25, "enable_thinking": False},
        "parameter_schema": {
            **CHAT_PARAMETER_SCHEMA,
            "enable_thinking": {
                "type": "boolean",
                "label": "Enable Thinking",
                "default": False,
            },
        },
    },
    {
        "model_id": "deepseek-v4-pro",
        "display_name": "DeepSeek V4 Pro",
        "provider": "dashscope",
        "task_type": "text_to_text",
        "adapter_name": "qwen_chat",
        "default_params": {"temperature": 0.7},
        "parameter_schema": CHAT_PARAMETER_SCHEMA,
    },
    {
        "model_id": "wan2.7-t2v",
        "display_name": "Wan 2.7 T2V",
        "provider": "dashscope",
        "task_type": "text_to_video",
        "adapter_name": "dashscope_t2v",
        "default_params": {
            "duration": 5,
            "resolution": "720P",
            "ratio": "9:16",
            "prompt_extend": False,
            "watermark": False,
        },
        "parameter_schema": T2V_PARAMETER_SCHEMA,
    },
    {
        "model_id": "wan2.6-image",
        "display_name": "Wan 2.6 Image",
        "provider": "dashscope",
        "task_type": "text_to_image",
        "adapter_name": "dashscope_image",
        "default_params": {
            "size": "1280*1280",
            "n": 1,
            "prompt_extend": True,
            "watermark": False,
            "enable_interleave": True,
        },
        "parameter_schema": IMAGE_PARAMETER_SCHEMA,
    },
    {
        "model_id": "wan2.7-image-pro",
        "display_name": "Wan 2.7 Image Pro",
        "provider": "dashscope",
        "task_type": "text_to_image",
        "adapter_name": "dashscope_image",
        "default_params": {
            "size": "1280*1280",
            "n": 1,
            "prompt_extend": True,
            "watermark": False,
            "enable_interleave": True,
        },
        "parameter_schema": WAN27_IMAGE_PARAMETER_SCHEMA,
    },
    {
        "model_id": "wan2.7-image",
        "display_name": "Wan 2.7 Image",
        "provider": "dashscope",
        "task_type": "text_to_image",
        "adapter_name": "dashscope_image",
        "default_params": {
            "size": "1280*1280",
            "n": 1,
            "prompt_extend": True,
            "watermark": False,
            "enable_interleave": True,
        },
        "parameter_schema": WAN27_IMAGE_PARAMETER_SCHEMA,
    },
    {
        "model_id": "wan2.6-r2v-flash",
        "display_name": "Wan 2.6 R2V Flash",
        "provider": "dashscope",
        "task_type": "reference_to_video",
        "adapter_name": "dashscope_r2v_flash",
        "default_params": {
            "duration": 5,
            "size": "720*1280",
            "audio": False,
            "shot_type": "single",
            "watermark": False,
        },
        "parameter_schema": R2V_PARAMETER_SCHEMA,
    },
    {
        "model_id": "wan2.7-i2v",
        "display_name": "Wan 2.7 I2V",
        "provider": "dashscope",
        "task_type": "image_to_video",
        "adapter_name": "dashscope_i2v",
        "default_params": {
            "duration": 10,
            "resolution": "720P",
            "prompt_extend": False,
            "watermark": False,
        },
        "parameter_schema": VIDEO_DURATION_SCHEMA,
    },
    {
        "model_id": "wan2.6-i2v-flash",
        "display_name": "Wan 2.6 I2V Flash",
        "provider": "dashscope",
        "task_type": "image_to_video",
        "adapter_name": "dashscope_i2v",
        "default_params": {
            "duration": 5,
            "resolution": "720P",
            "prompt_extend": True,
            "watermark": False,
            "audio": False,
            "shot_type": "default",
        },
        "parameter_schema": {
            **VIDEO_DURATION_SCHEMA,
            "audio": {"type": "boolean", "label": "Audio", "default": False},
            "shot_type": {
                "type": "string",
                "label": "Shot Type",
                "enum": ["default", "single", "multi"],
                "default": "default",
            },
        },
    },
    {
        "model_id": "happyhorse-1.0-i2v",
        "display_name": "HappyHorse I2V",
        "provider": "dashscope",
        "task_type": "image_to_video",
        "adapter_name": "dashscope_i2v",
        "default_params": {
            "duration": 5,
            "resolution": "720P",
            "watermark": False,
        },
        "parameter_schema": HAPPYHORSE_I2V_PARAMETER_SCHEMA,
    },
    *[{
        "model_id": model_id, "display_name": display_name, "provider": "dashscope",
        "task_type": "text_to_image", "adapter_name": "dashscope_qwen_image",
        "default_params": {"size": "1024*1024", "n": 1, "prompt_extend": True,
                           "enable_thinking": False, "watermark": False, "prompt_extend_mode": "direct"},
        "parameter_schema": QWEN3_IMAGE_PARAMETER_SCHEMA,
    } for model_id, display_name in (("qwen-image-3.0", "Qwen Image 3.0"), ("qwen-image-3.0-pro", "Qwen Image 3.0 Pro"))],
    *[{
        "model_id": model_id, "display_name": display_name, "provider": "dashscope",
        "task_type": "text_to_video", "adapter_name": "dashscope_wan3",
        "default_params": {"duration": 5, "resolution": "720P", "ratio": "adaptive", "audio": False,
                           "prompt_extend": False, "watermark": False},
        "parameter_schema": WAN3_VIDEO_PARAMETER_SCHEMA,
    } for model_id, display_name in (("wan3.0-video", "Wan 3.0 Video"), ("wan3.0-video-prime", "Wan 3.0 Video Prime"))],
    {
        "model_id": "deepseek-v4.1-flash", "display_name": "DeepSeek V4.1 Flash", "provider": "dashscope",
        "task_type": "prompt_rewrite", "adapter_name": "qwen_chat",
        "default_params": {"temperature": 0.7, "enable_thinking": False},
        "parameter_schema": {**CHAT_PARAMETER_SCHEMA,
                             "enable_thinking": {"type": "boolean", "label": "Enable Thinking", "default": False}},
    },
]

def _seed_capabilities(data: dict) -> dict:
    """Describe the existing registered adapters, not unverified provider features."""
    modes = {
        "video_understanding": ["text", "image_understanding", "video_understanding"],
        "text_to_text": ["text"], "prompt_rewrite": ["text"],
        "text_to_image": ["t2i"], "text_to_video": ["t2v"],
        "image_to_video": ["i2v"], "reference_to_video": ["r2v"],
    }[data["task_type"]]
    schema = data["parameter_schema"]
    duration = schema.get("duration")
    unit = "second" if duration else "image" if "t2i" in modes else "call"
    ratios = list(schema.get("ratio", {}).get("enum", []))
    for size in schema.get("size", {}).get("enum", schema.get("size", {}).get("presets", [])):
        width, height = (int(value) for value in size.split("*"))
        divisor = gcd(width, height)
        ratio = f"{width // divisor}:{height // divisor}"
        if ratio not in ratios:
            ratios.append(ratio)
    return {
        "modes": modes,
        "duration": {"min": duration["min"], "max": duration["max"], "step": 1} if duration else None,
        "resolutions": list(schema.get("resolution", {}).get("enum", [])),
        "aspect_ratios": ratios,
        "reference_images": {"max": 1} if set(modes) & {"i2v", "r2v", "image_understanding"} else None,
        "pricing": {"unit": unit, "credits_per_unit": 2.0 if unit == "image" else 1.0},
        "quality_tier": "standard", "agent_selectable": True,
        "notes": "演示单价，非供应商报价；参考图采用保守单图策略，其他范围沿用项目参数目录，接入真实模型前须核实。",
    }


for _seed in DEFAULT_MODELS:
    _seed["capabilities"] = _seed_capabilities(_seed)
    # This registered model is also used by the existing I2I workflow adapter.
    if _seed["model_id"] == "wan2.7-image":
        _seed["capabilities"]["modes"].append("i2i")
        _seed["capabilities"]["reference_images"] = {"max": 1}
    if _seed["model_id"] == "wan2.7-i2v":
        _seed["capabilities"]["modes"].append("first_last_frame")
        _seed["capabilities"]["reference_images"] = {"max": 2}

    if _seed["model_id"].startswith("qwen-image-3.0"):
        _seed["capabilities"].update(modes=["t2i", "i2i"], family="qwen-image-3.0", reference_images={"max": 3},
            pricing={"unit": "image", "credits_per_unit": 3.0 if _seed["model_id"].endswith("-pro") else 2.0},
            quality_tier="high" if _seed["model_id"].endswith("-pro") else "standard",
            notes="演示 credits，非供应商报价；最多3张参考图、6张输出；i2i不可使用agent提示词扩展。")
    if _seed["model_id"].startswith("wan3.0-video"):
        factor = 2.0 if _seed["model_id"].endswith("-prime") else 1.0
        _seed["capabilities"].update(modes=["t2v", "i2v", "first_last_frame", "r2v"], family="wan3.0",
            reference_images={"max": 10},
            pricing={"unit": "second", "credits_per_unit": 2.0 * factor,
                     "resolution_rates": {"480P": factor, "720P": 2.0 * factor, "1080P": 3.0 * factor},
                     "billing_basis": "input_plus_output_seconds"},
            quality_tier="fast" if factor == 2 else "standard",
            provider_capabilities={"reference_images": {"max": 10, "agent_enabled": True},
                "reference_video": {"max": 5, "max_total_seconds": 15, "agent_enabled": False, "adapter_enabled": False},
                "reference_audio": {"max": 5, "agent_enabled": False},
                "file": {"agent_enabled": False}, "link": {"agent_enabled": False},
                "video_edit": {"agent_enabled": False}, "video_extend": {"agent_enabled": False},
                "input_plus_output_seconds_max": 30},
            notes="演示 credits，非供应商报价；按分辨率及输入视频秒数+输出秒数估算。Prime为能力对齐的高速版，画质未实测。当前Agent只接入图片参考；视频/音频/file/link/编辑延长不自动启用，首尾画质未实测。")

# v3 agent turns settle by token usage (CONTRACTS V.3). A flat per-call price
# made one long-context turn cost as much as a second of video and exhausted
# the 20-credit planning allowance after ~20 turns (V-Gate3 real evaluation).
# Demo rates only; only the D-030 default text/vision models get them.
FACTORY_CALL_PRICING = {"unit": "call", "credits_per_unit": 1.0}
V3_TOKEN_RATES = {"deepseek-v4.1-flash": 0.01, "qwen3.7-plus": 0.02}
for _seed in DEFAULT_MODELS:
    if _seed["model_id"] in V3_TOKEN_RATES and _seed["capabilities"].get("pricing") == FACTORY_CALL_PRICING:
        _seed["capabilities"]["pricing"] = {**FACTORY_CALL_PRICING,
                                            "credits_per_1k_tokens": V3_TOKEN_RATES[_seed["model_id"]]}


# Recognize only the previous factory capability profile when upgrading existing
# rows. Preserve operator pricing, agent selection, limits and custom mode lists.
WAN3_LEGACY_CAPABILITIES = {item["model_id"]: deepcopy(item["capabilities"])
                           for item in DEFAULT_MODELS if item["adapter_name"] == "dashscope_wan3"}
for _seed in DEFAULT_MODELS:
    if _seed["model_id"] in WAN3_LEGACY_CAPABILITIES:
        caps = _seed["capabilities"]
        caps["modes"] += ["omni_reference", "video_edit", "video_extend"]
        caps["provider_capabilities"].update(
            reference_video={"max": 5, "max_total_seconds": 15, "agent_enabled": True, "adapter_enabled": True},
            reference_audio={"max": 5, "max_total_seconds": 15, "agent_enabled": True},
            file={"max": 1, "agent_enabled": True, "formats": ["txt", "md", "pdf"]},
            link={"agent_enabled": True, "strategy": "snapshot_file"},
            video_edit={"agent_enabled": True}, video_extend={"agent_enabled": True})
        caps["notes"] = ("演示 credits，非供应商报价；按分辨率及实际输入视频秒数+最终输出秒数估算。"
                         "全模态参考/编辑/延长须审核报价；网页转正文快照；总视频秒数≤30。Prime为高速版，画质未实测。")
        caps["transform_revision"] = 1


DEFAULT_MODEL_BY_ID = {model["model_id"]: model for model in DEFAULT_MODELS}


def _model_alias_key(value: str | None) -> str:
    return "".join(ch for ch in str(value or "").lower() if ch.isalnum())


MODEL_ALIAS_TO_ID = {}
for _model in DEFAULT_MODELS:
    MODEL_ALIAS_TO_ID[_model_alias_key(_model["model_id"])] = _model["model_id"]
    MODEL_ALIAS_TO_ID[_model_alias_key(_model["display_name"])] = _model["model_id"]
MODEL_ALIAS_TO_ID[_model_alias_key("happyhorse-i2v")] = "happyhorse-1.0-i2v"
MODEL_ALIAS_TO_ID[_model_alias_key("glm5-1")] = "glm-5.1"
MODEL_ALIAS_TO_ID[_model_alias_key("glm5.1")] = "glm-5.1"
MODEL_ALIAS_TO_ID[_model_alias_key("GLM5.1")] = "glm-5.1"


class ModelService:
    @staticmethod
    def supports_mode(model, mode: str) -> bool:
        capabilities = model.capabilities or {}
        if "modes" in capabilities:
            return mode in (capabilities.get("modes") or [])
        return mode in LEGACY_TASK_MODES.get(model.task_type, set())

    @staticmethod
    def supports_task_type(model, task_type: str) -> bool:
        # Scalar classifications remain compatible; provider-only metadata never
        # grants execution permission, and text roles keep their original guards.
        return model.task_type == task_type or bool(
            GENERATION_TASK_MODES.get(task_type, set()) & set((model.capabilities or {}).get("modes") or []))

    @staticmethod
    def model_family(model) -> str:
        return (model.capabilities or {}).get("family") or re.split(
            r"[-_](?:t2v|i2v|r2v|image)(?:[-_]|$)", model.model_id, flags=re.I)[0]

    @staticmethod
    def effective_params(model, params: dict | None = None) -> dict:
        """Use catalog defaults consistently for quoting and provider payloads."""
        effective = dict(model.default_params or {})
        minimum = ((model.capabilities or {}).get("duration") or {}).get("min")
        if minimum is not None:
            effective.setdefault("duration", minimum)
        effective.update(params or {})
        return effective

    @staticmethod
    def canonical_model_id(value: str | None) -> str | None:
        if value is None:
            return None
        raw = str(value).strip()
        if not raw:
            return None
        return MODEL_ALIAS_TO_ID.get(_model_alias_key(raw), raw)

    @staticmethod
    def seed_defaults() -> int:
        created = 0
        for data in DEFAULT_MODELS:
            existing = ModelRegistry.query.filter_by(model_id=data["model_id"]).first()
            if existing:
                changed = False
                # Backfill legacy rows, but never overwrite operator pricing/selection.
                if not existing.capabilities:
                    existing.capabilities = deepcopy(data["capabilities"])
                    changed = True
                caps = existing.capabilities or {}
                if (existing.model_id in V3_TOKEN_RATES and caps.get("pricing") == FACTORY_CALL_PRICING):
                    # Untouched factory price only; operator edits are preserved.
                    existing.capabilities = {**deepcopy(caps), "pricing": deepcopy(data["capabilities"]["pricing"])}
                    changed = True
                legacy = WAN3_LEGACY_CAPABILITIES.get(existing.model_id)
                caps = existing.capabilities or {}
                if (legacy and all(caps.get(key) == legacy.get(key)
                                   for key in ("modes", "provider_capabilities", "notes"))):
                    existing.capabilities = {**deepcopy(caps), **{
                        key: deepcopy(data["capabilities"][key])
                        for key in ("modes", "provider_capabilities", "notes", "transform_revision")}}
                    changed = True
                for field in (
                    "display_name",
                    "provider",
                    "task_type",
                    "adapter_name",
                    "parameter_schema",
                    "default_params",
                    "input_schema",
                    "output_schema",
                ):
                    value = data.get(field) or {}
                    if value and getattr(existing, field) != value:
                        setattr(existing, field, value)
                        changed = True
                if changed:
                    db.session.add(existing)
                continue
            model = ModelRegistry(
                model_id=data["model_id"],
                display_name=data["display_name"],
                provider=data["provider"],
                task_type=data["task_type"],
                adapter_name=data["adapter_name"],
                enabled=True,
                input_schema=data.get("input_schema") or {},
                parameter_schema=data.get("parameter_schema") or {},
                output_schema=data.get("output_schema") or {},
                default_params=data.get("default_params") or {},
                capabilities=deepcopy(data["capabilities"]),
            )
            db.session.add(model)
            created += 1
        ModelService.deduplicate_aliases(commit=False)
        db.session.commit()
        return created

    @staticmethod
    def list_models(task_type: str | None = None) -> list[ModelRegistry]:
        query = ModelRegistry.query
        models = query.order_by(ModelRegistry.provider.asc(), ModelRegistry.model_id.asc()).all()
        if task_type:
            models = [model for model in models if ModelService.supports_task_type(model, task_type)]
        return ModelService._unique_by_canonical_id(models)

    @staticmethod
    def get_model(model_id: str, require_enabled: bool = False) -> ModelRegistry:
        lookup_id = ModelService.canonical_model_id(model_id) or model_id
        model = ModelRegistry.query.filter_by(model_id=lookup_id).first()
        if not model and str(model_id).isdigit():
            model = db.session.get(ModelRegistry, int(model_id))
        if not model and lookup_id != model_id and lookup_id in DEFAULT_MODEL_BY_ID:
            ModelService.seed_defaults()
            model = ModelRegistry.query.filter_by(model_id=lookup_id).first()
        if not model and lookup_id != model_id:
            model = ModelRegistry.query.filter_by(model_id=model_id).first()
        if not model:
            raise AppError("MODEL_NOT_FOUND", "Model not found", 404)
        if require_enabled and not model.enabled:
            raise AppError("MODEL_NOT_FOUND", "Model is disabled", 400)
        return model

    @staticmethod
    def create_model(data: dict) -> ModelRegistry:
        canonical_id = ModelService.canonical_model_id(data["model_id"]) or data["model_id"]
        if canonical_id != data["model_id"]:
            data["model_id"] = canonical_id
        if ModelRegistry.query.filter_by(model_id=data["model_id"]).first():
            raise AppError("INVALID_INPUT", "Model id already exists", 409)
        display_alias_id = ModelService.canonical_model_id(data.get("display_name"))
        if display_alias_id and ModelRegistry.query.filter_by(model_id=display_alias_id).first():
            raise AppError(
                "INVALID_INPUT",
                "Display name duplicates an existing model. Use the existing model_id.",
                409,
            )
        model = ModelRegistry(**data)
        db.session.add(model)
        db.session.commit()
        return model

    @staticmethod
    def update_model(model_id: str, data: dict) -> ModelRegistry:
        model = ModelService.get_model(model_id)
        for field, value in data.items():
            if value is not None:
                setattr(model, field, value)
        db.session.commit()
        return model

    @staticmethod
    def set_enabled(model_id: str, enabled: bool) -> ModelRegistry:
        model = ModelService.get_model(model_id)
        model.enabled = enabled
        db.session.commit()
        return model

    @staticmethod
    def _unique_by_canonical_id(models: list[ModelRegistry]) -> list[ModelRegistry]:
        by_id: dict[str, ModelRegistry] = {}
        for model in models:
            canonical_id = ModelService.canonical_model_id(model.model_id) or model.model_id
            existing = by_id.get(canonical_id)
            if not existing:
                by_id[canonical_id] = model
                continue
            if existing.model_id != canonical_id and model.model_id == canonical_id:
                by_id[canonical_id] = model
            elif not existing.enabled and model.enabled:
                by_id[canonical_id] = model
        return list(by_id.values())

    @staticmethod
    def deduplicate_aliases(commit: bool = True) -> int:
        changed = 0
        all_models = ModelRegistry.query.all()
        existing_ids = {model.model_id for model in all_models}
        for model in all_models:
            canonical_id = ModelService.canonical_model_id(model.model_id)
            if canonical_id and canonical_id in DEFAULT_MODEL_BY_ID:
                canonical_data = DEFAULT_MODEL_BY_ID[canonical_id]
                if model.model_id == canonical_id:
                    if model.display_name != canonical_data["display_name"]:
                        model.display_name = canonical_data["display_name"]
                        changed += 1
                    continue
                if canonical_id not in existing_ids:
                    model.model_id = canonical_id
                    model.display_name = canonical_data["display_name"]
                    model.provider = canonical_data["provider"]
                    model.task_type = canonical_data["task_type"]
                    model.adapter_name = canonical_data["adapter_name"]
                    model.parameter_schema = canonical_data.get("parameter_schema") or {}
                    model.default_params = canonical_data.get("default_params") or {}
                    existing_ids.add(canonical_id)
                else:
                    model.enabled = False
                    if not model.display_name.endswith("(deprecated alias)"):
                        model.display_name = f"{model.display_name} (deprecated alias)"
                changed += 1
        if commit and changed:
            db.session.commit()
        return changed
