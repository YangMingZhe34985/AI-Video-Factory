"""Classic-path plans: run the classic workflow under a user's series and template (V.25)."""

from hashlib import sha256

from app.api import AppError
from app.models import Series, Template

# The Agent's private workspace is never a classic-path target (D-066).
INTERNAL_SERIES = frozenset({"agent_studio"})
INTERNAL_TEMPLATES = frozenset({"agent_workspace"})
CONTENT_PROMPT_TYPES = ("t2v", "first_frame_image", "i2v", "r2v_flash", "i2i")
MAX_LISTED_TEMPLATES = 50


def _public_template(template):
    return template.template_id not in INTERNAL_TEMPLATES and (template.series or "default") not in INTERNAL_SERIES


def prompt_summary(template, limit=120):
    from app.services.prompt_service import PromptService
    summary = {}
    for kind in CONTENT_PROMPT_TYPES:
        item = PromptService.get_active_for_template(template, kind)
        if item is not None and (item.content or "").strip():
            summary[kind] = {"version": item.version, "preview": item.content.strip()[:limit]}
    return summary


def catalog(series_id=None, query=None):
    """Public series/template catalog for planning; internal Agent storage is hidden."""
    series = {row.series_id: row for row in Series.query.order_by(Series.series_id).all()
              if row.series_id not in INTERNAL_SERIES}
    if series_id is not None and series_id not in series:
        raise AppError("SERIES_NOT_FOUND", "Series is not available for classic workflows", 404)
    rows = Template.query.order_by(Template.created_at.desc(), Template.id.desc()).all()
    needle = (query or "").casefold()
    groups = {key: [] for key in series if series_id in {None, key}}
    listed = 0
    for template in rows:
        key = template.series or "default"
        if not _public_template(template) or key not in groups or listed >= MAX_LISTED_TEMPLATES:
            continue
        if needle and needle not in f"{template.name}\n{template.description or ''}".casefold():
            continue
        groups[key].append({"template_id": template.template_id, "name": template.name,
                            "description": (template.description or "")[:300],
                            "prompt_types": prompt_summary(template)})
        listed += 1
    return [{"series_id": key, "name": series[key].name, "description": (series[key].description or "")[:300],
             "templates": items} for key, items in groups.items() if items or not needle]


def created_template_id(run_id, node_id):
    """Deterministic ID so a retried node reuses the template it created."""
    return "tpl_v3_" + sha256(f"{run_id}:{node_id}".encode()).hexdigest()[:20]


def resolve_target(target, run_id, node_id):
    """Validate a template target without writing; returns its public description."""
    if not isinstance(target, dict) or set(target) not in ({"template_id"}, {"series_id", "new_template_name"}):
        raise AppError("INVALID_TEMPLATE_TARGET", "template_target needs template_id, or series_id with new_template_name", 422,
                       payload={"field": "inputs.template_target"})
    if "template_id" in target:
        template = Template.query.filter_by(template_id=target["template_id"]).first()
        if template is None or not _public_template(template):
            raise AppError("TEMPLATE_NOT_FOUND", "Template is not available for classic workflows", 404,
                           payload={"field": "inputs.template_target.template_id"})
        series = Series.query.filter_by(series_id=template.series or "default").first()
        return {"mode": "existing", "template_id": template.template_id, "template_name": template.name,
                "series_id": template.series or "default", "series_name": series.name if series else template.series}
    series_id, name = target["series_id"], target["new_template_name"]
    series = Series.query.filter_by(series_id=series_id).first() if isinstance(series_id, str) else None
    if series is None or series.series_id in INTERNAL_SERIES:
        raise AppError("SERIES_NOT_FOUND", "New templates must be created under an existing series", 404,
                       payload={"field": "inputs.template_target.series_id"})
    if not isinstance(name, str) or not 1 <= len(name.strip()) <= 80:
        raise AppError("INVALID_TEMPLATE_TARGET", "New template name must contain 1 to 80 characters", 422,
                       payload={"field": "inputs.template_target.new_template_name"})
    template_id = created_template_id(run_id, node_id)
    existing = Template.query.filter_by(series=series.series_id, name=name.strip()).first()
    if existing is not None and existing.template_id != template_id:
        raise AppError("TEMPLATE_NAME_EXISTS", "A template with this name already exists in the series", 409,
                       payload={"field": "inputs.template_target.new_template_name"})
    return {"mode": "new", "template_id": template_id, "template_name": name.strip(),
            "series_id": series.series_id, "series_name": series.name}


# ---- run_workflow_template (V.25.2) ----

WORKFLOW_TOOL = "run_workflow_template"
BRANCH_NODES = {
    "reverse_prompts": ("reverse_prompts",),
    "rewrite_prompts": ("rewrite_prompts",),
    "r2v_prompt": ("reverse_prompts4r2v",),
    "t2v": ("submit_t2v", "poll_t2v"),
    "first_frame_image": ("submit_first_frame_image", "poll_first_frame_image"),
    "i2v": ("submit_i2v", "poll_i2v"),
    "r2v": ("submit_r2v_flash", "poll_r2v_flash"),
    "i2i_test": ("rewrite_t2i_to_i2i", "prepare_i2i_test_batch", "submit_i2i_test_image",
                 "poll_i2i_test_image", "submit_i2i_test_i2v", "poll_i2i_test_i2v"),
}
GENERATED_PROMPTS = {"reverse_prompts": ("t2v",), "rewrite_prompts": ("first_frame_image", "i2v"),
                     "r2v_prompt": ("r2v_flash",), "i2i_test": ("i2i",)}
# slot -> (branch, classic submit node, plan model mode)
SLOTS = {
    "t2v": ("t2v", "submit_t2v", "t2v"),
    "image": ("first_frame_image", "submit_first_frame_image", "t2i"),
    "i2v": ("i2v", "submit_i2v", "i2v"),
    "r2v": ("r2v", "submit_r2v_flash", "r2v"),
    "i2i_image": ("i2i_test", "submit_i2i_test_image", "i2i"),
    "i2i_video": ("i2i_test", "submit_i2i_test_i2v", "i2v"),
}
# Text and understanding nodes are frozen by the compiler under their classic node key.
TEXT_NODES = {"reverse_prompts": "video_understanding", "rewrite_prompts": "prompt_rewrite",
              "reverse_prompts4r2v": "prompt_rewrite", "rewrite_t2i_to_i2i": "prompt_rewrite"}
BRANCH_OUTPUTS = {"t2v": ("videos", "t2v_video"), "i2v": ("videos", "i2v_video"), "r2v": ("videos", "r2v_flash_video"),
                  "i2i_test": ("videos", "i2i_test_video"), "first_frame_image": ("images", "first_frame_image")}
VIDEO_ARTIFACTS = ("t2v_video", "i2v_video", "r2v_flash_video", "i2i_test_video")
IMAGE_ARTIFACTS = ("first_frame_image", "i2i_test_first_frame_image")
DELIVERY_OUTPUTS = {"video": "videos", "image": "images", "package": "package", "prompts": "prompts"}
VIDEO_BRANCHES = frozenset({"t2v", "i2v", "r2v", "i2i_test"})


def _issue(code, message, field=None, **details):
    return AppError(code, message, 422, payload={**({"field": field} if field else {}), **details})


def enabled_nodes(inputs):
    nodes = {key for branch in inputs["branches"] for key in BRANCH_NODES[branch]}
    if (inputs.get("prompts") or {}).get("i2i"):
        nodes.discard("rewrite_t2i_to_i2i")  # A supplied i2i prompt is tested as written.
    return sorted(nodes)


def test_count(inputs):
    return (inputs.get("i2i_test") or {}).get("test_count", 1)


def operations(inputs):
    """Every model-calling classic node -> (models key, calls)."""
    nodes = set(enabled_nodes(inputs))
    result = {key: (key, 1) for key in TEXT_NODES if key in nodes}
    for slot, (branch, key, _mode) in SLOTS.items():
        if key in nodes:
            result[key] = (slot, test_count(inputs) if branch == "i2i_test" else 1)
    return result


def produced_outputs(inputs):
    branches = set(inputs["branches"])
    packaged = inputs.get("package", True) is True and bool(branches & VIDEO_BRANCHES)
    return {field for branch, (field, _kind) in BRANCH_OUTPUTS.items() if branch in branches} | (
        {"package"} if packaged else set()) | {"prompts", "job_id", "template"}


def prompt_types(inputs):
    generated = {kind for branch in inputs["branches"] for kind in GENERATED_PROMPTS.get(branch, ())}
    return sorted(generated | {key for key, value in (inputs.get("prompts") or {}).items() if value})


def _check_shape(inputs):
    branches, prompts = set(inputs["branches"]), inputs.get("prompts") or {}
    for branch, kinds in GENERATED_PROMPTS.items():
        for kind in kinds:
            # The i2i rewrite is skipped when an i2i prompt is supplied for testing.
            if branch in branches and prompts.get(kind) and kind != "i2i":
                raise _issue("WORKFLOW_PROMPT_CONFLICT", f"Branch {branch} generates the {kind} prompt; do not also supply it",
                             f"inputs.prompts.{kind}")
    rules = [("source_video_artifact_id", "reverse_prompts" in branches, "reverse_prompts"),
             ("first_frame_artifact_id", "i2v" in branches and "first_frame_image" not in branches, "i2v without first_frame_image"),
             ("reference_artifact_ids", "r2v" in branches, "r2v"),
             ("i2i_test", "i2i_test" in branches, "i2i_test")]
    for field, needed, branch in rules:
        present = bool(inputs.get(field))
        if needed and not present:
            raise _issue("WORKFLOW_INPUT_MISSING", f"{branch} requires inputs.{field}", f"inputs.{field}")
        if present and not needed:
            raise _issue("WORKFLOW_INPUT_UNUSED", f"inputs.{field} is not used by the enabled branches", f"inputs.{field}")
    allowed = {slot for slot, (branch, _key, _mode) in SLOTS.items() if branch in branches}
    # Recompiling a normalized plan sees the compiler-frozen text node keys too.
    frozen = {key for key in TEXT_NODES if key in enabled_nodes(inputs)}
    for field in ("models", "model_params"):
        unknown = set(inputs.get(field) or {}) - allowed - frozen
        if unknown:
            raise _issue("WORKFLOW_MODEL_SLOT", f"Unknown or disabled model slots: {sorted(unknown)}",
                         f"inputs.{field}", allowed_slots=sorted(allowed))


def _validator_artifacts(inputs):
    result = {}
    if inputs.get("source_video_artifact_id"):
        result["source_video"] = {"artifact_id": inputs["source_video_artifact_id"]}
    if inputs.get("first_frame_artifact_id"):
        result["first_frame_image"] = {"artifact_id": inputs["first_frame_artifact_id"]}
    if inputs.get("reference_artifact_ids"):
        result["reference_images"] = [{"artifact_id": key} for key in inputs["reference_artifact_ids"]]
    if inputs.get("i2i_test"):
        result["i2i_test_batch"] = True
    return result


def _check_classic_dependencies(inputs):
    from app.services.workflow_service import WorkflowService
    from app.services.workflow_validator import WorkflowValidator
    enabled = set(enabled_nodes(inputs)) | {"export_manifest"}
    all_keys = {node.node_key for node in WorkflowService.list_nodes()}
    prompts = {key: value for key, value in (inputs.get("prompts") or {}).items() if value}
    result = WorkflowValidator.validate(enabled_nodes=sorted(enabled), disabled_nodes=sorted(all_keys - enabled),
                                        initial_prompts=prompts, initial_artifacts=_validator_artifacts(inputs))
    errors = result.get("errors") or []
    if errors or result.get("required_inputs"):
        first = errors[0] if errors else {}
        required = ", ".join(str(item.get("key", item) if isinstance(item, dict) else item)
                             for item in list(result.get("required_inputs") or [])[:5])
        raise _issue("WORKFLOW_DEPENDENCY_MISSING", first.get("message") or f"Classic workflow inputs are missing: {required}",
                     "inputs.branches", errors=errors[:5], required_inputs=list(result.get("required_inputs") or [])[:5])


def _text_params(model, node_key):
    from app.services.model_service import ModelService
    from app.services.workflow_service import WorkflowService
    from app.tools import model_guard
    defaults = ModelService.effective_params(model)
    defaults.update((WorkflowService.get_node(node_key).config or {}).get("model_params") or {})
    return model_guard.validate_params(model, {key: value for key, value in defaults.items()
                                               if key in (model.parameter_schema or {})})


def freeze_models(node, request_spec, run):
    """Resolve and freeze every model-calling node's model and parameters into inputs."""
    from app.plans.aspect import generation_params
    from app.plans.compiler import brief_for_run
    from app.plans.model_selection import select_generation_model
    from app.tools import model_guard
    inputs = node["inputs"]
    aspect = (request_spec or {}).get("aspect_ratio")
    seconds = brief_for_run(run).target_duration_sec
    _check_shape(inputs)
    _check_classic_dependencies(inputs)
    models, params = dict(inputs.get("models") or {}), dict(inputs.get("model_params") or {})
    frozen_models, frozen_params = {}, {}
    couple = (inputs.get("i2i_test") or {}).get("mode") == "couple"
    for node_key, (slot, _calls) in operations(inputs).items():
        if node_key in TEXT_NODES:
            model = model_guard.effective_model(TEXT_NODES[node_key], node_key, None)
            if models.get(slot) not in {None, model.model_id} or params.get(slot) not in (None, _text_params(model, node_key)):
                raise _issue("WORKFLOW_MODEL_SLOT", "Text and understanding nodes use the classic configured model",
                             f"inputs.models.{slot}")
            frozen_models[slot], frozen_params[slot] = model.model_id, _text_params(model, node_key)
            continue
        mode = SLOTS[slot][2]
        count = {"t2v": 0, "t2i": 0, "i2v": 1, "i2i": 2 if couple else 1,
                 "r2v": len(inputs.get("reference_artifact_ids") or [])}[mode]
        supplied = dict(params.get(slot) or {})
        if mode in {"t2v", "i2v", "r2v"} and seconds is not None:
            supplied.setdefault("duration", int(seconds) if float(seconds).is_integer() else seconds)
        try:
            model, validated = select_generation_model(request_spec, mode, models.get(slot), supplied,
                reference_count=count, run=run, params_factory=lambda candidate, supplied=supplied, mode=mode:
                    generation_params(node, candidate, supplied, aspect, mode, {}))
        except AppError as error:
            error.payload = {"field": f"inputs.models.{slot}", **(error.payload if isinstance(error.payload, dict) else {})}
            raise
        if slot in {"image", "i2i_image"} and validated.get("n", 1) != 1:
            raise _issue("INVALID_OUTPUT_COUNT", "Classic image nodes produce one image per call", f"inputs.model_params.{slot}")
        frozen_models[slot], frozen_params[slot] = model.model_id, validated
    inputs["models"], inputs["model_params"] = frozen_models, frozen_params
    # Classic packages are built around a video; prompts-only or image-only Jobs are not packable.
    inputs["package"] = inputs.get("package", True) is True and bool(set(inputs["branches"]) & VIDEO_BRANCHES)
    return inputs


def quote(inputs):
    """Price frozen inputs with current catalog prices; also the per-call admission bound."""
    from app.services.model_service import ModelService
    from app.tools.budget import estimate_model_cost
    calls, total, seconds = {}, 0.0, 0.0
    for node_key, (slot, count) in operations(inputs).items():
        model = ModelService.get_model(inputs["models"][slot], require_enabled=True)
        params = inputs["model_params"].get(slot) or {}
        unit = estimate_model_cost(model, params)
        calls[node_key] = {"model_id": model.model_id, "params": params, "unit_cost": unit, "calls": count}
        total += unit * count
        if node_key in {"submit_t2v", "submit_i2v", "submit_r2v_flash", "submit_i2i_test_i2v"}:
            seconds += float(params.get("duration") or 0) * count
    return {"calls": calls, "total": round(total, 6), "output_video_seconds": seconds}


def estimate(node):
    priced = quote(node["inputs"])
    return {"node_id": node["id"], "model_id": None, "mode": "workflow", "estimated_cost": priced["total"],
            "input_video_seconds": 0.0, "output_video_seconds": priced["output_video_seconds"], "pricing": {}}


def template_write(node, run):
    target = resolve_target(node["inputs"].get("template_target"), run.run_id, node["id"])
    return {"node_id": node["id"], **target, "prompt_types": prompt_types(node["inputs"])}


# ---- execution binding (V.25.4) ----

# Classic submit nodes whose provider prompt is the stored prompt verbatim.
VERBATIM_PROMPTS = {"submit_t2v": "t2v", "submit_first_frame_image": "first_frame_image",
                    "submit_i2v": "i2v", "submit_r2v_flash": "r2v_flash"}


def classic_submit(adapter, payload):
    """Run a classic node's provider call with classic semantics inside Agent/MQ workers."""
    from app.adapters.qwen_chat import classic_json_fallback
    token = classic_json_fallback.set(True)
    try:
        return adapter.submit(payload)
    finally:
        classic_json_fallback.reset(token)


def _mismatch(message):
    return AppError("PLAN_APPROVAL_MISMATCH", message, 409)


def initial_prompts(job):
    """Seeded prompt versions are immutable rows; later LLM versions are not approval inputs."""
    from app.models import PromptVersion
    result = {}
    for kind, ref in ((job.config or {}).get("initial_prompt_refs") or {}).items():
        item = PromptVersion.query.filter_by(prompt_id=(ref or {}).get("prompt_id")).first()
        if item is not None:
            result[kind] = {"content": item.content, "version": item.version}
    return result


def bind(task, job):
    """Check a launched Job against the frozen node; returns per-call price bounds."""
    inputs, config = task.inputs, job.config or {}
    calls = operations(inputs)
    models = {key: inputs["models"][slot] for key, (slot, _count) in calls.items()}
    params = {key: inputs["model_params"][slot] for key, (slot, _count) in calls.items() if inputs["model_params"].get(slot)}
    if config.get("node_models") != models or (config.get("node_model_params") or {}) != params:
        raise _mismatch("Job models differ from the approved workflow node")
    if config.get("agent_workflow") != {"branches": inputs["branches"], "test_count": test_count(inputs)}:
        raise _mismatch("Job branches differ from the approved workflow node")
    expected = {key: value for key, value in (inputs.get("prompts") or {}).items() if value}
    if {kind: item["content"] for kind, item in initial_prompts(job).items()} != expected:
        raise _mismatch("Job prompts differ from the approved workflow node")
    priced = quote(inputs)
    if priced["total"] > task.estimated_cost + 1e-6:
        raise AppError("MODEL_PRICE_CHANGED", "Workflow price increased; a new approval is required", 409)
    return {key: item["unit_cost"] for key, item in priced["calls"].items()}


def validate_submit(run, task, model, inputs, params, operation, adapter_name):
    from app.plans.execution import fingerprint
    from app.tools.budget import estimate_model_cost
    snapshot = task.state["job_snapshot"]
    config = snapshot["config"]
    if (operation not in (config.get("node_models") or {}) or model.model_id != config["node_models"][operation]
            or params != (config.get("node_model_params") or {}).get(operation, {}) or not model.enabled):
        raise _mismatch("Submission model or parameters changed after approval")
    effective = "dashscope_multimodal_sync" if model.model_id.startswith("wan2.7-image") else model.adapter_name
    if adapter_name not in {None, model.adapter_name, effective}:
        raise _mismatch("Submission adapter differs from approval")
    if any(fingerprint(run, key) != value for key, value in task.state.get("input_fingerprints", {}).items()):
        raise AppError("PLAN_INPUT_CHANGED", "Source bytes changed while queued", 409)
    seeded = snapshot["prompts"].get(VERBATIM_PROMPTS.get(operation))
    if seeded is not None and (inputs or {}).get("prompt") != seeded["content"]:
        raise AppError("PLAN_INPUT_CHANGED", "Submission prompt differs from the approved initial prompt", 409)
    bound = (task.state.get("workflow_unit_costs") or {}).get(operation)
    if bound is None or estimate_model_cost(model, params) > bound + 1e-6:
        raise AppError("MODEL_PRICE_CHANGED", "Model price increased; a new approval is required", 409)


def job_outputs(task, job):
    from app.models import Artifact
    from app.services.job_package_service import JobPackageService
    from app.services.prompt_service import PromptService
    inputs = task.inputs
    rows = Artifact.query.filter_by(job_id=job.id).order_by(Artifact.id).all()
    generated = [row for row in rows if not (row.meta or {}).get("source_artifact_id")]
    for branch, (_field, kind) in BRANCH_OUTPUTS.items():
        if branch in inputs["branches"] and not any(row.artifact_type == kind for row in generated):
            raise AppError("PLAN_OUTPUT_MISSING", f"Classic branch {branch} produced no {kind}", 502)
    prompts = {}
    for kind in CONTENT_PROMPT_TYPES:
        item = PromptService.get_active_for_template(job.template, kind, job_id=job.id)
        if item is not None and (item.content or "").strip():
            prompts[kind] = {"prompt_id": item.prompt_id, "version": item.version, "content": item.content}
    missing = set(prompt_types(inputs)) - set(prompts)
    if missing:
        raise AppError("PLAN_OUTPUT_MISSING", f"Classic workflow produced no {sorted(missing)} prompt", 502)
    package = JobPackageService.create_or_refresh(job)["artifact"]["artifact_id"] if inputs.get("package", True) else None
    template = job.template
    return {"job_id": job.job_id, "prompts": prompts, "package": package,
            "template": {"template_id": template.template_id, "name": template.name,
                         "series_id": template.series or "default",
                         "created": bool((template.config or {}).get("agent_created"))},
            "videos": [row.artifact_id for row in generated if row.artifact_type in VIDEO_ARTIFACTS],
            "images": [row.artifact_id for row in generated if row.artifact_type in IMAGE_ARTIFACTS]}
