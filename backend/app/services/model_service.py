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


DEFAULT_MODELS = [
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
        "model_id": "glm5-1",
        "display_name": "GLM 5.1",
        "provider": "dashscope",
        "task_type": "text_to_text",
        "adapter_name": "qwen_chat",
        "default_params": {"temperature": 0.25},
        "parameter_schema": CHAT_PARAMETER_SCHEMA,
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
        "model_id": "happyhorse-i2v",
        "display_name": "HappyHorse I2V",
        "provider": "dashscope",
        "task_type": "image_to_video",
        "adapter_name": "dashscope_i2v",
        "default_params": {
            "duration": 5,
            "resolution": "720P",
            "prompt_extend": False,
            "watermark": False,
        },
        "parameter_schema": VIDEO_DURATION_SCHEMA,
    },
]

DEFAULT_MODEL_BY_ID = {model["model_id"]: model for model in DEFAULT_MODELS}


def _model_alias_key(value: str | None) -> str:
    return "".join(ch for ch in str(value or "").lower() if ch.isalnum())


MODEL_ALIAS_TO_ID = {}
for _model in DEFAULT_MODELS:
    MODEL_ALIAS_TO_ID[_model_alias_key(_model["model_id"])] = _model["model_id"]
    MODEL_ALIAS_TO_ID[_model_alias_key(_model["display_name"])] = _model["model_id"]


class ModelService:
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
            )
            db.session.add(model)
            created += 1
        ModelService.deduplicate_aliases(commit=False)
        db.session.commit()
        return created

    @staticmethod
    def list_models(task_type: str | None = None) -> list[ModelRegistry]:
        query = ModelRegistry.query
        if task_type:
            query = query.filter_by(task_type=task_type)
        models = query.order_by(ModelRegistry.provider.asc(), ModelRegistry.model_id.asc()).all()
        return ModelService._unique_by_canonical_id(models)

    @staticmethod
    def get_model(model_id: str, require_enabled: bool = False) -> ModelRegistry:
        lookup_id = ModelService.canonical_model_id(model_id) or model_id
        model = ModelRegistry.query.filter_by(model_id=lookup_id).first()
        if not model and str(model_id).isdigit():
            model = db.session.get(ModelRegistry, int(model_id))
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
