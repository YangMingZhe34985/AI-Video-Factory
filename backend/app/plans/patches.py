"""Pure Patch application and read-only, evidence-bound incremental quotes."""

from copy import deepcopy
from decimal import Decimal

from pydantic import ValidationError

from app.agent.plan_versions import inputs_hash, require_current_version
from app.agents.schemas import PlanDraft, finite_json
from app.agents.workspace import require_artifact
from app.api import AppError
from app.extensions import db
from app.models import AgentDelegation, AgentWorkspaceItem, PlanNodeTask
from app.plans.compiler import authoring_plan, compile_plan
from app.plans.dry_run import dry_run
from app.plans import execution
from app.plans.patch_schemas import PatchDraft
from app.plans.patch_intent import automatic_intent_reasons, verified_assessment
from app.plans.patch_origin import normalize_authors, verified_patch_author
from app.tools.budget import BudgetGuard
from app.tools.spec import ToolContext

GENERATORS = frozenset({"generate_image", "animate_shot", "generate_video", "transform_video"})
DELIVERY = frozenset({"compose_video", "probe_media", "qc_video", "package_story"})
REPAIRABLE = frozenset({"content_policy", "invalid_parameters", "qc_failed"})
BLOCKED_CODES = frozenset({"MODEL_PRICE_CHANGED", "PLAN_INPUT_CHANGED", "PLAN_ARTIFACT_UNAVAILABLE",
    "BUDGET_EXCEEDED", "MODEL_NOT_FOUND", "MODEL_DISABLED", "UNAUTHORIZED", "AUTHENTICATION_FAILED",
    "INVALID_API_KEY", "INSUFFICIENT_BALANCE", "CONFIGURATION_ERROR"})


def normalize_patch(raw):
    value = raw.model_dump(mode="json") if isinstance(raw, PatchDraft) else raw
    try:
        return PatchDraft.model_validate(finite_json(value)).model_dump(mode="json")
    except ValidationError as error:
        raise AppError("INVALID_PATCH", "Patch does not match the authoring contract", 422) from error


def patch_digest(raw):
    return inputs_hash(normalize_patch(raw))


def apply_patch_draft(base, draft, *, trusted_author=None):
    """Apply explicit operations only; broken references stay compiler errors."""
    draft = normalize_patch(draft)
    value = PlanDraft.model_validate(authoring_plan(base)).model_dump(mode="json")
    upgrade = draft.get("identity_upgrade")
    if upgrade is not None:
        if value.get("character_references"):
            raise AppError("PLAN_IDENTITY_UPGRADE_FORBIDDEN", "An existing identity catalog cannot be replaced by an upgrade", 422)
        story_ref = upgrade.get("story_ref")
        if value.get("story_ref") and story_ref and value["story_ref"] != story_ref:
            raise AppError("PLAN_IDENTITY_UPGRADE_FORBIDDEN", "An identity upgrade cannot change the fixed story reference", 422)
        value["character_references"] = deepcopy(upgrade["character_references"])
        if story_ref is not None:
            value["story_ref"] = deepcopy(story_ref)
    nodes = {node["id"]: node for node in value["nodes"]}
    original_ids = set(nodes)
    for op in draft["ops"]:
        kind = op["op"]
        target = op["node"]["id"] if kind == "insert_node" else op["node_id"]
        if kind == "insert_node":
            if target in original_ids or target in nodes:
                raise AppError("INVALID_PATCH_TARGET", "Inserted node already exists", 422)
            nodes[target] = deepcopy(op["node"])
        elif target not in original_ids or target not in nodes:
            raise AppError("INVALID_PATCH_TARGET", "Patch target does not exist in the base Plan", 422)
        elif kind == "update_inputs":
            nodes[target]["inputs"] = {**nodes[target]["inputs"], **deepcopy(op["inputs"])}
        elif kind == "replace_node":
            nodes[target] = deepcopy(op["node"])
        else:
            del nodes[target]
    for op in draft["ops"]:
        if op["op"] == "insert_node" and op.get("before"):
            before = nodes.get(op["before"])
            if before is None:
                raise AppError("INVALID_PATCH_TARGET", "Insertion ordering target is unavailable", 422)
            before["depends_on"] = list(dict.fromkeys([*before["depends_on"], op["node"]["id"]]))
    if trusted_author is not None:
        normalize_authors(nodes, draft, trusted_author)
    value["nodes"] = list(nodes.values())
    return value


def _workspace(run, ref):
    row = AgentWorkspaceItem.query.filter_by(run_id=run.run_id, key=ref.get("key"), version=ref.get("version")).first()
    if row is None:
        raise AppError("INVALID_PATCH_EVIDENCE", "Patch workspace evidence does not belong to this Run", 403)
    return row


def _review(run, record, draft):
    review = record.get("director_review") or {}
    director = db.session.get(AgentDelegation, review.get("delegation_id")) if type(review.get("delegation_id")) is int else None
    if (review.get("verdict") not in {"approve", "revise"} or director is None or director.agent != "director"
            or director.run_id != run.run_id or record.get("review_delegation_id") != director.id
            or review.get("base_version") != draft["base_version"] or review.get("draft_hash") != patch_digest(draft)
            or not isinstance(review.get("request_key"), str) or not review["request_key"]):
        raise AppError("PATCH_REVIEW_REQUIRED", "Patch requires a verified Director review", 403)
    row = _workspace(run, review.get("review_ref") or {})
    if (row.kind != "patch" or row.author_agent != "director" or row.delegation_id != director.id
            or patch_digest(row.payload) != patch_digest(draft)):
        raise AppError("PATCH_REVIEW_REQUIRED", "Director review does not bind this exact draft", 403)
    verified_assessment(run, record, patch_digest(draft))
    authorship = verified_patch_author(run, record, draft)
    return inputs_hash({"review": review, "authorship": authorship})


def _evidence(run, draft):
    task_ids = set()
    for item in draft["evidence_refs"]:
        if "task_id" in item:
            task = db.session.get(PlanNodeTask, item["task_id"])
            if task is None or task.run_id != run.run_id:
                raise AppError("INVALID_PATCH_EVIDENCE", "Patch task evidence does not belong to this Run", 403)
            task_ids.add(task.id)
        elif "artifact_id" in item:
            require_artifact(item["artifact_id"], ToolContext(role="production", budget_scope=run.run_id), run=run)
        else:
            _workspace(run, item["workspace_ref"])
    return task_ids


def _closure(roots, *dags):
    found = set(roots)
    while True:
        more = found | {child for dag in dags for parent in found for child in dag.get("children", {}).get(parent, [])}
        if more == found:
            return found
        found = more


def source_digest(task):
    return inputs_hash({name: deepcopy(getattr(task, name)) for name in ("id", "run_id", "plan_version", "node_id", "attempt", "status",
        "inputs_hash", "inputs", "output", "state", "artifact_ids", "invocation_id", "job_id", "error")})


def source_proof(task):
    return {"task_id": task.id, "source_version": task.plan_version, "node_id": task.node_id,
            "tool": task.state.get("tool"), "inputs_hash": task.inputs_hash, "inputs": deepcopy(task.inputs),
            "input_fingerprints": deepcopy(task.state.get("input_fingerprints", {})),
            "output": deepcopy(task.output), "output_fingerprints": deepcopy(task.state.get("output_fingerprints", {})),
            "artifact_ids": deepcopy(task.artifact_ids), "invocation_id": task.invocation_id, "job_id": task.job_id,
            "state": deepcopy(task.state), "error": deepcopy(task.error), "status": task.status,
            "attempt": task.attempt, "run_id": task.run_id, "source_digest": source_digest(task)}


def _semantic_inputs(data):
    value = deepcopy(data)
    value.pop("plan_version", None)
    return value


def _safe_success(run, task, registry):
    if not execution.usable(run, task):
        return False
    expected = inputs_hash({"tool": task.state.get("tool"), "inputs": task.inputs,
                            "sources": task.state.get("input_fingerprints", {})})
    if not task.state.get("resolved") or task.inputs_hash != expected:
        return False
    found = set()
    try:
        if task.state.get("tool") == "select_image":
            from app.plans.choices import receipt_for_task
            receipt_for_task(run, task)
        spec = registry.get(task.state["tool"])
        for field, kind in spec.io_types.get("outputs", {}).items():
            if kind.removesuffix("[]") in execution.MEDIA_TYPES:
                value = task.output.get(field)
                if value is None and field == "compressed_artifact_id" and not task.inputs.get("compress_output"):
                    continue
                for artifact_id in execution._ids(value, kind):
                    if execution.fingerprint(run, artifact_id, kind.removesuffix("[]")) != task.state.get("output_fingerprints", {}).get(artifact_id):
                        return False
                    found.add(artifact_id)
        return found == set(task.artifact_ids or [])
    except (AppError, TypeError, KeyError):
        return False


def _unknown(task):
    error = task.error or {}
    return error.get("category") == "submit_unknown" or error.get("submission_state") == "unknown"


def _historical_pin(run, task):
    """Follow actual applied approvals, never trust a task's retention flag alone."""
    if not task.state.get("retained_by_only") or not task.state.get("continuity_risk_accepted"):
        return False
    records = (run.snapshot or {}).get("v3_patches", {})
    current, seen = task, set()
    while current.id not in seen and len(seen) < 200:
        seen.add(current.id)
        record = records.get(current.state.get("patch_id"), {})
        approval, quote = record.get("approval", {}), record.get("quote", {})
        if record.get("status") != "applied" or approval.get("version") != current.plan_version:
            return False
        if (current.node_id in quote.get("kept_node_ids", []) and approval.get("scope") == "only"
                and approval.get("automatic") is False):
            return True
        if current.node_id not in quote.get("reused_node_ids", []):
            return False
        previous = db.session.get(PlanNodeTask, current.state.get("reused_from"))
        if (previous is None or previous.run_id != run.run_id or previous.node_id != current.node_id
                or previous.plan_version >= current.plan_version or previous.status != "success"
                or previous.inputs_hash != current.inputs_hash or previous.inputs != current.inputs
                or previous.output != current.output
                or previous.state.get("output_fingerprints") != current.state.get("output_fingerprints")):
            return False
        current = previous
    return False


def _inflight(run, issue):
    from app.plans.patch_execution import assert_patch_idle
    tasks = PlanNodeTask.query.filter_by(run_id=run.run_id).all()
    try:
        assert_patch_idle(run)
    except AppError as error:
        issue(error.code, error.message)
    return tasks


def repair_budget(run):
    pool = (run.snapshot or {}).get("v3_repair", {})
    limit = float(pool.get("budget_limit", (run.snapshot or {}).get("v3_execution", {}).get("repair_budget_credits", 0)))
    claims = pool.get("repair_claims", {})
    automatic = [item for item in claims.values() if item.get("automatic")]
    spent = sum(float(item.get("credits", 0)) for item in automatic)
    counts = {}
    for item in automatic:
        for node_id in set(item.get("node_ids", [])):
            counts[node_id] = counts.get(node_id, 0) + 1
    return {"limit": limit, "remaining": max(0.0, limit - spent), "node_attempts": counts}


def _automatic(run, record, draft, roots, affected, tasks, evidence_ids, cost):
    pool = repair_budget(run)
    reasons = automatic_intent_reasons(verified_assessment(run, record, patch_digest(draft)))
    if verified_patch_author(run, record, draft) is None:
        reasons.append("PATCH_AUTHOR_UNVERIFIED")
    if draft.get("identity_upgrade") is not None:
        reasons.append("IDENTITY_UPGRADE_REQUIRES_REVIEW")
    trigger = record.get("trigger") or {}
    if trigger.get("kind") != "failure" or set(trigger.get("node_ids", [])) != roots:
        reasons.append("FAILURE_TRIGGER_REQUIRED")
    trigger_ids = set(trigger.get("task_ids", []))
    if any(op["op"] != "update_inputs" or not op["inputs"] or set(op["inputs"]) - {"prompt"}
           or not isinstance(op["inputs"].get("prompt"), str) or not op["inputs"]["prompt"].strip() for op in draft["ops"]):
        reasons.append("PROMPT_ONLY_REQUIRED")
    for node_id in roots:
        task = tasks.get(node_id)
        failure = task.error or {} if task else {}
        if (task is None or task.status != "failed" or task.id not in evidence_ids or task.id not in trigger_ids
                or failure.get("category") not in REPAIRABLE or _unknown(task)
                or failure.get("code") in BLOCKED_CODES or task.state.get("tool") not in GENERATORS):
            reasons.append("REPAIRABLE_FAILURE_REQUIRED")
    if any(tasks.get(node_id) and tasks[node_id].status == "success" for node_id in affected):
        reasons.append("COMPLETED_OUTPUT_AFFECTED")
    if any(pool["node_attempts"].get(node_id, 0) >= 2 for node_id in roots):
        reasons.append("AUTO_REPAIR_LIMIT")
    if cost > pool["remaining"] + 1e-6:
        reasons.append("REPAIR_BUDGET_EXCEEDED")
    return {"eligible": not reasons, "reasons": sorted(set(reasons)), "remaining_credits": pool["remaining"],
            "node_attempts": pool["node_attempts"]}


def quote_patch(run, record, scope=None, registry=None):
    """Inspect a server record; never authorize, mutate, launch or call a model."""
    with db.session.no_autoflush:
        return _quote(run, record, scope=scope, registry=registry)


def _quote(run, record, *, scope, registry):
    if registry is None:
        from app.tools import build_v3_registry
        registry = build_v3_registry()
    draft = normalize_patch(record.get("draft"))
    base = require_current_version(run, draft["base_version"])
    approval = (run.snapshot or {}).get("v3_execution", {})
    if (approval.get("approved_version") != base.version or approval.get("approval_hash") != inputs_hash(base.plan)
            or record.get("status") in {"applied", "rejected"}):
        raise AppError("PATCH_BASE_NOT_APPROVED", "A Patch requires the current approved Plan", 409)
    review_hash = _review(run, record, draft)
    evidence_ids = _evidence(run, draft)
    scope = scope or draft["scope"]
    if scope not in {"only", "cascade"}:
        raise AppError("INVALID_PATCH_SCOPE", "Unknown Patch scope", 422)
    issues, warnings = [], []
    def issue(code, message, node_id=None):
        value = {"code": code, "message": message, "node_id": node_id}
        if value not in issues:
            issues.append(value)
    try:
        author = verified_patch_author(run, record, draft)
        candidate = apply_patch_draft(base.plan, draft, trusted_author=author["agent"] if author else None)
    except AppError as error:
        candidate = authoring_plan(base.plan)
        issue(error.code, error.message)
    compiled = compile_plan(candidate, run, registry=registry, plan_version=base.version + 1)
    checked = dry_run(compiled, registry=registry)
    issues.extend(checked["issues"])
    old_compiled = compile_plan(base.plan, run, registry=registry, plan_version=base.version)
    old_dag = base.check.get("dag") or old_compiled["dag"]
    roots = {op["node"]["id"] if op["op"] == "insert_node" else op["node_id"] for op in draft["ops"]}
    affected = _closure(roots, old_dag, compiled["dag"])
    old_nodes = {node["id"]: node for node in base.plan["nodes"]}
    nodes = {node["id"]: node for node in compiled["plan"].get("nodes", [])}
    removed = set(old_nodes) - set(nodes)
    all_tasks = _inflight(run, issue)
    tasks = {}
    for task in sorted(all_tasks, key=lambda row: (row.attempt, row.id)):
        if task.plan_version == base.version:
            tasks[task.node_id] = task
    costs = {item["node_id"]: item for item in compiled["estimates"]["nodes"]}
    decisions, sources, known_outputs, source_files = {}, {}, {}, {}
    for node_id in compiled["dag"]["order"]:
        node, task = nodes[node_id], tasks.get(node_id)
        estimate = costs.get(node_id, {})
        action = "execute"
        force = node_id in affected or node["tool"] in DELIVERY
        successful = bool(task and task.status == "success")
        usable = _safe_success(run, task, registry) if successful else False
        if successful and not usable and (not force or node["tool"] in GENERATORS):
            issue("PATCH_SOURCE_UNAVAILABLE", "已完成结果失效，请先恢复原产物。", node_id)
        trigger = record.get("trigger") or {}
        if (scope == "only" and node_id in roots and successful and trigger.get("kind") != "user_revision"
                and node_id not in trigger.get("node_ids", [])):
            issue("PATCH_COMPLETED_SCOPE", "修改无关的已完成节点需要明确选择连带修改。", node_id)
        if node["tool"] not in DELIVERY:
            if node_id not in affected and task and task.status == "failed":
                action = "preserve_failure"
            elif node_id not in affected and task and task.status in {"stale", "cancelled"}:
                issue("PATCH_SOURCE_UNAVAILABLE", "范围外节点已取消或失效，不能隐式重新提交。", node_id)
            elif (scope == "only" and node_id in affected - roots and node["tool"] in GENERATORS and usable
                    and node == old_nodes.get(node_id)):
                action = "retain"
            elif not force and usable:
                if node == old_nodes.get(node_id) and _historical_pin(run, task):
                    action = "reuse"
                else:
                    try:
                        selection = None
                        if node["tool"] == "select_image":
                            from app.plans.choices import receipt_for_task
                            selection = receipt_for_task(run, task)
                        data, fingerprints, _digest = execution.resolve_node(run, node, base.version + 1,
                            known_outputs, registry, choice_receipt=selection)
                        if (_semantic_inputs(data) == _semantic_inputs(task.inputs)
                                and fingerprints == task.state.get("input_fingerprints", {})):
                            action = "reuse"
                    except (AppError, KeyError):
                        pass
                if action != "reuse":
                    issue("PATCH_SOURCE_CHANGED", "范围外结果输入已改变，需要重新规划受影响范围。", node_id)
        cost = float(estimate.get("estimated_cost", 0)) if action == "execute" else 0.0
        decisions[node_id] = {"action": action, "source_task_id": task.id if task and action != "execute" else None,
            "estimated_cost": cost, "force_rerun": force and action == "execute",
            "input_video_seconds": estimate.get("input_video_seconds", 0),
            "output_metadata": deepcopy(compiled["output_metadata"].get(node_id, {}))}
        if task and action != "execute":
            sources[node_id] = source_proof(task)
            if action != "preserve_failure":
                known_outputs[node_id] = deepcopy(task.output)
                source_files.update(deepcopy(task.state.get("output_fingerprints", {})))
        if action == "retain":
            warnings.append({"code": "RETAINED_HISTORICAL_OUTPUT", "node_id": node_id,
                             "message": "保留此节点原生成结果；它使用旧输入，衔接效果可能改变。"})
    for artifact_id in compiled.get("source_artifact_ids", []):
        source_files[artifact_id] = execution.fingerprint(run, artifact_id)
    continuation_ids = {key for key, value in decisions.items() if value["action"] == "execute" and (
        key not in affected or (nodes[key] == old_nodes.get(key) and (tasks.get(key) is None or (
            tasks[key].status == "pending" and not tasks[key].job_id and not tasks[key].invocation_id))))}
    repair_ids = {key for key, value in decisions.items() if value["action"] == "execute"} - continuation_ids
    def total(ids):
        return float(sum((Decimal(str(decisions[key]["estimated_cost"])) for key in ids), Decimal(0)))
    repair_cost, continuation_cost = total(repair_ids), total(continuation_ids)
    incremental = float(Decimal(str(repair_cost)) + Decimal(str(continuation_cost)))
    automatic = _automatic(run, record, draft, roots, affected, tasks, evidence_ids, repair_cost)
    for code in automatic["reasons"]:
        if code in {"PATCH_INTENT_UNCERTAIN", "PATCH_INTENT_CHANGED"}:
            warnings.append({"code": code, "node_id": None, "message":
                "修订改变了用户点名内容，需要人工确认。" if code == "PATCH_INTENT_CHANGED"
                else "尚未确认修订保留原需求，需要人工确认。"})
    manual_can_apply = not issues
    try:
        BudgetGuard.check(run.run_id, run.request["budget_limit"], incremental + automatic["remaining_credits"])
    except AppError as error:
        manual_can_apply = False
        warnings.append({"code": "MANUAL_BUDGET_RESERVED", "node_id": None,
                         "message": "人工批准需保留未使用的自动修复额度，当前总预算不足。"})
    if automatic["eligible"]:
        try:
            BudgetGuard.check(run.run_id, run.request["budget_limit"], incremental + max(0, automatic["remaining_credits"] - repair_cost))
        except AppError:
            automatic["eligible"] = False
            automatic["reasons"] = sorted(set([*automatic["reasons"], "TOTAL_BUDGET_EXCEEDED"]))
    if not manual_can_apply and not automatic["eligible"] and not issues:
        issue("BUDGET_EXCEEDED", "修复、继续执行及预留额度超过剩余预算。")
    if issues:
        automatic["eligible"] = False
        automatic["reasons"] = sorted(set([*automatic["reasons"], "PATCH_NOT_EXECUTABLE"]))
    internal = {"base_version": base.version, "target_version": base.version + 1, "scope": scope,
        "patch_hash": patch_digest(draft), "review_hash": review_hash, "candidate_hash": inputs_hash(compiled["plan"]),
        "affected_node_ids": sorted(affected), "removed_node_ids": sorted(removed), "nodes": decisions, "sources": sources,
        "source_task_signatures": {str(task.id): source_digest(task) for task in tasks.values()},
        "source_fingerprints": source_files, "auto_node_ids": sorted(roots), "repair_node_ids": sorted(repair_ids),
        "repair_cost": repair_cost, "continuation_cost": continuation_cost, "automatic": automatic}
    quote = {"patch_id": record["patch_id"], "base_version": base.version, "scope": scope,
        "can_apply": not issues, "manual_can_apply": manual_can_apply and not issues,
        "affected_node_ids": sorted(affected), "execute_node_ids": sorted(key for key, item in decisions.items() if item["action"] == "execute"),
        "reused_node_ids": sorted(key for key, item in decisions.items() if item["action"] == "reuse"),
        "kept_node_ids": sorted(key for key, item in decisions.items() if item["action"] == "retain"),
        "removed_node_ids": sorted(removed), "continuation_node_ids": sorted(continuation_ids),
        "estimated_credits": {"repair": repair_cost, "continuation": continuation_cost, "total": incremental},
        "node_costs": [{"node_id": key, "action": item["action"], "estimated_cost": item["estimated_cost"],
            "input_video_seconds": costs.get(key, {}).get("input_video_seconds", 0),
            "output_video_seconds": costs.get(key, {}).get("output_video_seconds", 0)} for key, item in decisions.items()],
        "automatic": {key: automatic[key] for key in ("eligible", "reasons", "remaining_credits")},
        "warnings": warnings, "issues": issues, "demo": True}
    quote["quote_id"] = inputs_hash({"run_id": run.run_id, "decisions": internal, "quote": quote,
                                    "repair_ledger": (run.snapshot or {}).get("v3_repair", {})})
    return {"compiled": compiled, "dry_run": checked, "decisions": internal, "quote": quote}
