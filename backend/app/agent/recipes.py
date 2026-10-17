"""Bridge v2 understanding into the established storyboard production nodes."""

from copy import deepcopy
from fractions import Fraction
from math import ceil, floor, gcd, isfinite, lcm

from app.agent.director_lite import model_question, resolved_request
from app.agent.model_selection import select_for_request, validate_generation_model, video_policy_for_request
from app.agent.plan_spec import PlanSpec, RemixShotSpec, shot_cost
from app.agent.protocol import validate_plan
from app.agent.sources import describe_source, source_for_run
from app.api import AppError
from app.models import AgentRun, Job, PromptVersion
from app.skills.budget import BudgetGuard


def prepare_transition(state):
    spec = resolved_request(state)
    try:
        video = select_for_request(spec, "i2v")
    except AppError as error:
        return {"request_spec": spec, "open_questions": [model_question("i2v", error)], "status": "planning"}
    target = spec.get("target_duration_sec")
    maximum = video.capabilities["duration"]["max"]
    update = {
        "request_spec": spec, "goal": spec["summary"], "mode": "from_scratch",
        "video_model_policy": video_policy_for_request(spec), "open_questions": [],
        "status": "planning", "shot_count": min(20, max(1, ceil((target or maximum) / maximum))),
    }
    row = AgentRun.query.filter_by(run_id=state["run_id"]).one()
    # The original request remains authoritative for legacy Creative.
    update["goal"] = row.request["text"]
    if spec["recipe_hint"] == "remix":
        source = source_for_run(row)
        analysis_job = state["analysis_jobs"][source.artifact_id]
        job = Job.query.filter_by(job_id=analysis_job).one()
        prompt = PromptVersion.query.filter_by(
            job_id=job.id, prompt_type="t2v", prompt_key="default", is_active=True,
        ).one()
        info = describe_source(source)
        update.update(mode="remix", source=info, analysis_job_id=job.job_id,
                      analysis={"job_id": job.job_id, "prompt_id": prompt.prompt_id, "content": prompt.content},
                      shot_count=min(20, max(1, ceil((target or info["duration"]) / maximum))))
    return update


def _duration_number(value):
    if isinstance(value, bool) or not isinstance(value, (int, float)) or not isfinite(value):
        raise AppError("MODEL_CAPABILITY_MISMATCH", "Duration bounds must be finite numbers", 422)
    return Fraction(str(value))


def _integer_grid(origin, step):
    """Intersect a rational capability grid with integer provider durations."""
    scale = lcm(origin.denominator, step.denominator)
    offset, stride = int(origin * scale), int(step * scale)
    divisor = gcd(stride, scale)
    if offset % divisor:
        raise AppError("MODEL_CAPABILITY_MISMATCH", "Duration grid contains no integer provider value", 422)
    period = scale // divisor
    index = (-offset // divisor * pow(stride // divisor, -1, period)) % period if period > 1 else 0
    return origin + index * step, step * period


def distribute_duration(target, count, model):
    """Allocate at most 20 clips without walking a potentially microscopic grid."""
    if isinstance(count, bool) or not isinstance(count, int) or not 1 <= count <= 20:
        raise AppError("INVALID_PLAN", "Storyboard requires between 1 and 20 clips", 422)
    target = _duration_number(target)
    bounds = (model.capabilities or {}).get("duration") or {}
    rule = (model.parameter_schema or {}).get("duration") or {}
    origin, high = _duration_number(bounds.get("min")), _duration_number(bounds.get("max"))
    step = _duration_number(bounds["step"]) if bounds.get("step") is not None else None
    if origin <= 0 or high < origin or (step is not None and step <= 0):
        raise AppError("MODEL_CAPABILITY_MISMATCH", "Duration range and step must be positive", 422)
    if rule.get("type") not in {"integer", "number"}:
        raise AppError("MODEL_CAPABILITY_MISMATCH", "Provider must expose numeric duration parameters", 422)
    low = max(origin, _duration_number(rule.get("min", float(origin))))
    high = min(high, _duration_number(rule.get("max", float(high))))
    if low > high:
        raise AppError("MODEL_CAPABILITY_MISMATCH", "Provider and capability duration ranges do not intersect", 422)

    if "enum" in rule:
        # Enumerations are already finite; never expand them onto the grid.
        choices = set()
        for raw in rule["enum"]:
            if isinstance(raw, bool) or not isinstance(raw, (int, float)) or not isfinite(raw):
                continue
            value = Fraction(str(raw))
            if (low <= value <= high and (rule["type"] != "integer" or value.denominator == 1)
                    and (step is None or ((value - origin) / step).denominator == 1)):
                choices.add(value)
        if not choices:
            raise AppError("MODEL_CAPABILITY_MISMATCH", "No supported enumerated clip duration is available", 422)
        # Each pass allocates exactly one clip, balancing the remaining target.
        # Nonuniform provider enums may not realize the target exactly; the
        # caller retains its total-duration tolerance check and editable draft.
        values, remaining = [], target
        for clips_left in range(count, 0, -1):
            chosen = min(choices, key=lambda value: (abs(value - remaining / clips_left), value))
            values.append(chosen)
            remaining -= chosen
    else:
        if rule["type"] == "integer":
            origin, step = _integer_grid(origin, step) if step is not None else (Fraction(0), Fraction(1))
        if step is None:
            values = [max(low, min(high, target / count))] * count
        else:
            first = origin + ceil((low - origin) / step) * step
            last_index = floor((high - first) / step)
            if last_index < 0:
                raise AppError("MODEL_CAPABILITY_MISMATCH", "Duration ranges contain no common grid point", 422)
            desired = max(Fraction(0), min(Fraction(count * last_index), (target - count * first) / step))
            total_index = min({floor(desired), ceil(desired)}, key=lambda value: (abs(value - desired), value))
            index, extra = divmod(total_index, count)
            values = [first + index * step] * (count - extra) + [first + (index + 1) * step] * extra

    # The final shared guard also checks defaults, resolution and provider types.
    durations = [int(value) if value.denominator == 1 else float(value) for value in values]
    for value in set(durations):
        validate_generation_model(model, "i2v", {"duration": value}, reference_count=1)
    return durations


def complete_transition_draft(raw, state):
    """Fill omitted generation defaults; explicit LLM values remain reviewable."""
    plan = deepcopy(raw)
    video = select_for_request(state["request_spec"], "i2v")
    target = state["request_spec"].get("target_duration_sec")
    if not target:
        target = state.get("source", {}).get("duration") or video.capabilities["duration"]["max"]
    durations = distribute_duration(target, len(plan["shots"]), video)
    for index, shot in enumerate(plan["shots"]):
        if shot.get("action") == "keep":
            continue
        if not shot.get("video_model_id"):
            shot["video_model_id"] = video.model_id
        shot.setdefault("video_params", {}).setdefault("duration", durations[index])
    return plan


def validate_transition_plan(raw, state, *, enforce_duration=False):
    """Keep v1 shape/parameter checks, with v2 capabilities and remaining budget."""
    plan = validate_plan(
        raw, state["shot_count"], float("inf"), state["video_model_policy"],
        mode=state["mode"], source_duration=state.get("source", {}).get("duration"),
    )
    parsed = PlanSpec.model_validate(plan)
    total = 0
    for shot in parsed.shots:
        if isinstance(shot, RemixShotSpec) and shot.action == "keep":
            total += shot.source_end - shot.source_start
            continue
        video = select_for_request(state["request_spec"], "i2v", shot.video_model_id)
        shot.video_params = validate_generation_model(video, "i2v", shot.video_params, reference_count=1)
        total += shot.video_params["duration"]
        if not isinstance(shot, RemixShotSpec) or shot.first_frame_mode == "generate":
            image = select_for_request(state["request_spec"], "t2i", shot.image_model_id)
            shot.image_params = validate_generation_model(image, "t2i", shot.image_params)
    target = state["request_spec"].get("target_duration_sec")
    if enforce_duration and target and abs(total - target) > state["request_spec"]["duration_tolerance_sec"]:
        raise AppError("INVALID_PLAN", "Storyboard duration differs from the requested duration", 422,
                       payload={"target_duration_sec": target, "planned_duration_sec": total})
    BudgetGuard.check(state["run_id"], state["budget_limit"], sum(shot_cost(shot) for shot in parsed.shots))
    return parsed.model_dump(mode="json")
