"""Story-only graph nodes: immutable drafts, image previews and two review gates."""

from copy import deepcopy
from typing import TypedDict

from flask import current_app
from langgraph.types import interrupt

from app.agent import plan_versions as versions
from app.agent import preview_production as previews
from app.agent.director_v2 import director_v2
from app.agent.plan_check import check_plan
from app.agent.prompt_smith import write_plan_prompts
from app.agent.story_actions import changed_shots, missing_prompt_issues, parse_plan, selected_targets, stale_targets, validate_command
from app.api import AppError
from app.extensions import db
from app.models import AgentRun


class StoryState(TypedDict, total=False):
    story_package: dict
    plan_version: int
    story_parent_version: int
    story_revision_key: str
    story_repair_attempted: bool
    story_editing: bool
    story_changed_shots: list[str]
    story_pending_command: dict
    preview_targets: list[list[str]]
    preview_return_status: str
    preview_stage: str
    estimates: dict
    previews: dict
    prompt_issues: list[dict]


def _run(state):
    return AgentRun.query.filter_by(run_id=state["run_id"]).one()


def _stored(state):
    return versions.get_version(_run(state), state["plan_version"])


def _view(version):
    return {"plan": version.plan, "story_package": version.story_package, "plan_version": version.version,
            "plan_issues": version.check.get("issues", []), "estimates": version.check.get("estimates", {})}


def _operation(run, key):
    receipt = (run.snapshot or {}).get("plan_operations", {}).get(key)
    return versions.get_version(run, receipt["version"]) if receipt else None


def _save(run, plan, story, checked, *, key, author="system", base=None):
    existing = _operation(run, key)
    if existing:
        return existing
    return versions.create_version(run, plan, story,
        {"issues": checked["issues"], "estimates": checked["estimates"]},
        author=author, base_version=base, operation_key=key)


def _prepare_available(run, version, *, targets=None, force_targets=()):
    # Invalid drafts remain editable; unresolved generated references are not
    # sent to a generation tool. A later explicit repair can create the task.
    for target in targets if targets is not None else previews.targets_for(version, phase="all"):
        try:
            previews.prepare_previews(run, version, targets=[target], force_targets=force_targets)
        except AppError as error:
            if error.code not in {"PREVIEW_INCOMPLETE", "INVALID_REFERENCE", "MODEL_CAPABILITY_MISMATCH", "INVALID_INPUT", "INVALID_PRODUCTION_PLAN"}:
                raise


def _remember_models(run, previous, plan):
    overrides = dict((run.snapshot or {}).get("story_model_overrides", {}))
    before = {shot["shot_id"]: shot for shot in previous["shots"]}
    for shot in plan["shots"]:
        old = before.get(shot["shot_id"], {})
        for field in ("motion", "first_frame", "end_frame"):
            model_id = (shot.get(field) or {}).get("model_id")
            if model_id and model_id != (old.get(field) or {}).get("model_id"):
                overrides[f"{shot['shot_id']}:{field}"] = model_id
    run.snapshot = {**(run.snapshot or {}), "story_model_overrides": overrides}
    db.session.commit()


def nodes(registry):
    def draft(state):
        run = _run(state)
        current = versions.current_version(run)
        plan = deepcopy(state["plan"])
        parent = current.version if current else 0
        plan["plan_version"] = parent + 1
        return {"plan": plan, "story_parent_version": parent,
                "story_revision_key": "director:repair" if state.get("story_repair_attempted") else "director:initial"}

    def prompts(state):
        if len(state["plan"]["shots"]) > current_app.config.get("AGENT_MAX_STORY_SHOTS", 30):
            return {"prompt_issues": [{"code": "INVALID_PRODUCTION_PLAN", "message": "镜头数超过上限，请先调整计划。", "shot_id": None}]}
        # Schema-valid but business-invalid plans should still be repairable even
        # if model selection prevents writing prompts for a particular shot.
        try:
            return write_plan_prompts(state, registry, shot_ids=state.get("story_changed_shots") if state.get("story_editing") else None)
        except AppError as error:
            if error.code in {"MODEL_CAPABILITY_MISMATCH", "MODEL_NOT_FOUND", "INVALID_REFERENCE", "BUDGET_EXCEEDED"}:
                return {"prompt_issues": [{"code": error.code, "message": error.message, "shot_id": None}]}
            raise

    def check(state):
        run = _run(state)
        key = state["story_revision_key"]
        saved = _operation(run, key)
        if not saved:
            checked = check_plan(state["plan"], state["story_package"], state["request_spec"], run=run,
                                 preview_credits=previews.remaining_preview_cost(run, state["plan"], state["story_package"]))
            checked["issues"].extend(state.get("prompt_issues", []))
            checked["issues"].extend(missing_prompt_issues(checked["plan"]))
            saved = _save(run, checked["plan"], state["story_package"], checked, key=key,
                          author="user" if state.get("story_editing") else "director", base=state["story_parent_version"])
        update = _view(saved)
        if state.get("story_editing"):
            _prepare_available(run, saved)
            update.update(status="awaiting_storyboard", story_editing=False,
                          story_changed_shots=[], last_command_id=state["story_pending_command"]["command_id"])
        elif update["plan_issues"]:
            update["status"] = "awaiting_storyboard" if state.get("story_repair_attempted") else "planning"
        else:
            update["status"] = "planning"
        return update

    def repair(state):
        try:
            result = director_v2(state, registry, issues=state["plan_issues"])
        except AppError as error:
            if error.code not in {"BUDGET_EXCEEDED", "MODEL_CAPABILITY_MISMATCH", "MODEL_NOT_FOUND"}:
                raise
            return {"story_repair_attempted": True, "status": "awaiting_storyboard"}
        if not result.get("plan"):
            # Keep the existing editable draft if automatic repair needs new
            # decisions; no silent model substitution or extra generation.
            return {"story_repair_attempted": True, "status": "awaiting_storyboard"}
        return {**result, "story_repair_attempted": True, "status": "planning"}

    def begin(state):
        run, version = _run(state), _stored(state)
        characters = previews.targets_for(version, phase="characters")
        targets = characters or previews.targets_for(version, phase="keyframes")
        return {"preview_targets": [list(item) for item in targets],
                "preview_return_status": "awaiting_characters" if characters else "awaiting_storyboard",
                "preview_stage": "characters" if characters else "keyframes", "status": "previewing"}

    def launch(state):
        run, version = _run(state), _stored(state)
        targets = [tuple(item) for item in state.get("preview_targets", [])]
        previews.prepare_previews(run, version, targets=targets)
        previews.launch_previews(run, version, targets, registry)
        return {"status": "previewing"}

    def collect(state):
        run, version = _run(state), _stored(state)
        report = previews.poll_previews(run, version, registry)
        tasks = {(item.target_type, item.target_id): item for item in versions.list_tasks(run, version.version)}
        targets = [tuple(item) for item in state.get("preview_targets", [])]
        pending = any(tasks.get(target) and tasks[target].status in {"pending", "running"} for target in targets)
        if pending:
            return {"status": "previewing", "previews": previews.preview_view(run, version)}
        # Bind a successful portrait once, then persist a new immutable version.
        try:
            plan, story = previews.bind_character_references(run, version)
        except AppError as error:
            if error.code != "PREVIEW_INCOMPLETE":
                raise
            return {**_view(version), "status": state["preview_return_status"],
                    "previews": previews.preview_view(run, version)}
        if plan != version.plan or story != version.story_package:
            checked = check_plan(plan, story, state["request_spec"], run=run,
                                 preview_credits=previews.remaining_preview_cost(run, plan, story))
            version = _save(run, checked["plan"], story, checked,
                            key=f"bind:{version.version}", base=version.version)
            _prepare_available(run, version, targets=previews.targets_for(version, phase="characters")
                               if state["preview_return_status"] == "awaiting_characters" else None)
        return {**_view(version), "status": state["preview_return_status"],
                "previews": previews.preview_view(run, version)}

    def wait(_state):
        interrupt({"kind": "previews"})
        return {}

    def review(state):
        kind = "characters" if state["status"] == "awaiting_characters" else "storyboard"
        command = interrupt({"kind": kind, "plan_version": state["plan_version"]})
        return {"story_pending_command": command}

    def apply(state):
        run, version = _run(state), _stored(state)
        command = state["story_pending_command"]
        action, key = command["action"], command["command_id"]
        existing = _operation(run, key)
        # Replays of a committed edit use its version without repeating budget
        # checks whose spent total may already include its newly launched work.
        if not existing:
            validate_command(run, command, review_status=state["status"])
        if action == "reject":
            return {"status": "cancelled", "last_command_id": key}
        if action == "approve_storyboard":
            return {"status": "storyboard_approved", "approved": True, "last_command_id": key}
        if action == "edit_plan":
            if existing:
                _prepare_available(run, existing)
                return {**_view(existing), "status": "awaiting_storyboard", "last_command_id": key}
            plan = parse_plan(command["plan"])
            _remember_models(run, version.plan, plan)
            plan["plan_version"] = version.version + 1
            return {"plan": plan, "story_package": version.story_package,
                    "story_parent_version": version.version, "story_revision_key": key,
                    "story_editing": True, "story_changed_shots": changed_shots(version.plan, plan), "status": "planning"}
        if action == "approve_characters":
            story, plan = deepcopy(version.story_package), deepcopy(version.plan)
            changed = set()
            for edit in command.get("edits", []):
                character = next(item for item in story["characters"] if item["character_id"] == edit["character_id"])
                if edit.get("lock_description"):
                    character["lock_description"] = edit["lock_description"]
                if edit.get("generate_prompt"):
                    character["reference"]["generate_prompt"] = edit["generate_prompt"]
                changed.add(character["character_id"])
            if existing:
                version = existing
            elif changed:
                plan["plan_version"] = version.version + 1
                affected = [shot["shot_id"] for shot in plan["shots"] if changed.intersection(shot["character_ids"])]
                plan = write_plan_prompts({**state, "plan": plan, "story_package": story}, registry, shot_ids=affected)["plan"]
                checked = check_plan(plan, story, state["request_spec"], run=run,
                                 preview_credits=previews.remaining_preview_cost(run, plan, story))
                version = _save(run, checked["plan"], story, checked, key=key, author="user", base=version.version)
            _prepare_available(run, version, targets=previews.targets_for(version, phase="characters"))
            from app.agent.story_actions import require_previews
            try:
                require_previews(run, version, "characters")
            except AppError as error:
                if error.code != "PREVIEW_INCOMPLETE":
                    raise
                return {**_view(version), "status": "awaiting_characters", "last_command_id": key}
            if version.check.get("issues"):
                return {**_view(version), "status": "awaiting_storyboard", "last_command_id": key}
            targets = previews.targets_for(version, phase="keyframes")
            return {**_view(version), "preview_targets": [list(item) for item in targets], "preview_stage": "keyframes",
                    "preview_return_status": "awaiting_storyboard", "status": "previewing", "last_command_id": key}
        # A regeneration is explicit and always keeps the old product/version.
        targets = stale_targets(run, version) if action == "regenerate_stale" else selected_targets(version, command)
        if existing:
            version = existing
        else:
            plan, story = deepcopy(version.plan), deepcopy(version.story_package)
            if command.get("prompt"):
                kind, target_id = targets[0]
                if kind == "character":
                    next(item for item in story["characters"] if item["character_id"] == target_id)["reference"]["generate_prompt"] = command["prompt"]
                else:
                    field = "end_frame" if kind == "end_frame" else "first_frame"
                    next(item for item in plan["shots"] if item["shot_id"] == target_id)[field]["prompt"] = command["prompt"]
            version = _save(run, plan, story, version.check, key=key, author="user", base=version.version)
        # Force at most once: a new version has no attempts until preparation;
        # node replay finds them and will reuse its exact idempotency key.
        for target in targets:
            if versions.latest_task(run, version.version, *target) is None:
                previews.prepare_previews(run, version, targets=[target], force_targets=[target])
        _prepare_available(run, version, targets=previews.targets_for(version, phase="characters")
                           if state["status"] == "awaiting_characters" else None)
        return {**_view(version), "preview_targets": [list(item) for item in targets], "preview_stage": "regenerate",
                "preview_return_status": state["status"], "status": "previewing", "last_command_id": key}

    return {"story_v2_draft": draft, "story_v2_prompts": prompts, "story_v2_check": check,
            "story_v2_repair": repair, "story_v2_begin": begin, "story_v2_launch": launch,
            "story_v2_collect": collect, "story_v2_wait": wait, "story_v2_review": review, "story_v2_apply": apply}
