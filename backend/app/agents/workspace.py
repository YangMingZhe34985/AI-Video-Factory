"""Run-scoped append-only Agent decisions with durable write replay."""

from copy import deepcopy
from hashlib import sha256
import json
import re

from pydantic import TypeAdapter, ValidationError

from app.agent.attachments import attachment_for_owner
from app.agent.plan_versions import _lock_run
from app.agent.search.scope import require_run
from app.agents.schemas import WORKSPACE_KINDS, WorkspaceKey, WorkspaceRef, validate_payload
from app.api import AppError
from app.extensions import db
from app.models import AgentDelegation, AgentWorkspaceItem, Artifact, ToolInvocation
from app.tools.job_backed import resolve_artifact
from app.tools.specs.get_task_status import require_v3_job_scope
from app.utils.time_utils import as_utc


def require_context(ctx):
    """Workspace identity always comes from the runtime, never tool arguments."""
    if (not ctx.caller_agent or ctx.role != ctx.caller_agent
            or type(ctx.delegation_id) is not int or ctx.delegation_id < 1):
        raise AppError("INVALID_AGENT_CONTEXT", "Workspace requires a server-owned Agent identity", 403)
    run = require_run(ctx)
    delegation = AgentDelegation.query.populate_existing().filter_by(
        id=ctx.delegation_id, run_id=run.run_id, agent=ctx.caller_agent).first()
    if delegation is None or (run.request or {}).get("schema_version") != 3:
        raise AppError("INVALID_AGENT_CONTEXT", "Delegation does not belong to this Agent and Run", 403)
    return run, delegation


def _key(value):
    try:
        return TypeAdapter(WorkspaceKey).validate_python(value)
    except ValidationError as error:
        raise AppError("INVALID_WORKSPACE_KEY", "Invalid workspace key", 422) from error


def require_artifact(artifact_id, ctx, *, run=None):
    """Accept uploaded, researched or generated artifacts from this Run only."""
    if not isinstance(artifact_id, str) or not artifact_id:
        raise AppError("INVALID_WORKSPACE_PAYLOAD", "Artifact references must be non-empty IDs", 422)
    run = run or require_context(ctx)[0]
    if artifact_id in (run.request or {}).get("attachment_ids", []):
        return attachment_for_owner(artifact_id, run.owner_id, run_id=run.run_id)
    artifact = Artifact.query.filter_by(artifact_id=artifact_id).first()
    if artifact and artifact.artifact_type in {"agent_reference_image", "agent_reference_document"}:
        return attachment_for_owner(artifact_id, run.owner_id, run_id=run.run_id)
    if artifact is None:
        raise AppError("ATTACHMENT_NOT_FOUND", "Workspace artifact is unavailable", 404)
    require_v3_job_scope(artifact.job, ctx)
    return resolve_artifact(artifact_id, ctx=ctx)


def _artifact_ids(value, *, plan_refs=False):
    """Recognized structured references only; text never confers ownership."""
    found = set()
    if isinstance(value, list):
        for child in value:
            found.update(_artifact_ids(child, plan_refs=plan_refs))
    elif isinstance(value, dict):
        if plan_refs and set(value) == {"ref"}:
            return found
        for key, child in value.items():
            if (key in {"artifact", "artifact_id", "attachment_id", "reference_id"}
                    or key.endswith("_artifact_id")) and child is not None:
                if plan_refs and isinstance(child, dict) and set(child) in ({"ref"}, {"artifact"}):
                    found.update(_artifact_ids(child, plan_refs=True))
                    continue
                if not isinstance(child, str) or not child:
                    raise AppError("INVALID_WORKSPACE_PAYLOAD", "Artifact references must be IDs", 422)
                found.add(child)
            elif key in {"artifact_ids", "attachment_ids", "reference_ids"} or key.endswith("_artifact_ids"):
                if plan_refs and isinstance(child, dict) and set(child) == {"ref"}:
                    continue
                if not isinstance(child, list):
                    raise AppError("INVALID_WORKSPACE_PAYLOAD", "Artifact lists must contain IDs", 422)
                for item in child:
                    if isinstance(item, str) and item:
                        found.add(item)
                    elif plan_refs and isinstance(item, dict) and set(item) in ({"ref"}, {"artifact"}):
                        found.update(_artifact_ids(item, plan_refs=True))
                    else:
                        raise AppError("INVALID_WORKSPACE_PAYLOAD", "Artifact lists must contain IDs or Plan references", 422)
            else:
                found.update(_artifact_ids(child, plan_refs=plan_refs))
    return found


def validate_artifact_references(payload, ctx, *, plan_refs=False):
    run, _delegation = require_context(ctx)
    ids = sorted(_artifact_ids(payload, plan_refs=plan_refs))
    for artifact_id in ids:
        require_artifact(artifact_id, ctx, run=run)
    return ids


def _validate_brief(payload, run):
    actual = {item["attachment_id"]: item["kind"] for item in payload["attachments"]}
    expected = {}
    for artifact_id in (run.request or {}).get("attachment_ids", []):
        artifact = attachment_for_owner(artifact_id, run.owner_id, run_id=run.run_id)
        expected[artifact_id] = (artifact.meta or {}).get("media", {}).get("kind")
    if actual != expected:
        raise AppError("INVALID_WORKSPACE_PAYLOAD", "Brief must describe every uploaded attachment with its original kind", 422)
    text = (run.request or {}).get("text", "")
    if payload.get("target_duration_sec") is not None:
        source = payload.get("duration_source_text")
        if not payload.get("duration_mode") or not source or source not in text:
            raise AppError("INVALID_DURATION_SOURCE",
                "An explicit duration requires duration_mode and duration_source_text quoted from the user's original request", 422)
    constraints = payload["constraints"]
    frozen = (run.snapshot or {}).get("v3_revision_constraints")
    if frozen is not None and constraints != frozen:
        raise AppError("REVISION_CONSTRAINT_CONFLICT", "Revision must preserve original hard constraints", 422)
    if any(not value or value not in text for value in constraints["model_preferences"] + constraints["model_exclusions"]):
        raise AppError("INVALID_WORKSPACE_PAYLOAD", "Model constraints must preserve the original user wording", 422)
    transform = payload.get("transform")
    literal_urls = {value.rstrip(".,;!?") for value in re.findall(r'https?://[^\s<>"，。！？；）)]+', text)}
    if transform and any(url not in literal_urls for url in transform["reference_urls"]):
        raise AppError("URL_NOT_ALLOWED", "Reference URLs must occur in the original user request", 422)


def _validate_research(payload, run):
    """Reconstruct observed evidence from successful receipts, not Agent claims."""
    from app.agent.research_spec import validate_dossier

    receipts = ToolInvocation.query.filter_by(budget_scope=run.run_id, status="success").filter(
        ToolInvocation.tool_name.in_({"web_search", "image_search", "fetch_page", "download_reference", "analyze_images"})
    ).order_by(ToolInvocation.id).all()
    fetched = set()
    analyses, hits, downloads = {}, [], []
    for row in receipts:
        inputs, output = row.input_payload or {}, row.output_payload or {}
        if row.tool_name in {"web_search", "image_search"}:
            for hit in output.get("results", []):
                hits.append({**hit, "kind": "web" if row.tool_name == "web_search" else "image",
                             "fetched_at": output.get("fetched_at", row.created_at.isoformat())})
        elif row.tool_name == "fetch_page":
            if (inputs.get("run_id") == run.run_id and output.get("url") == inputs.get("url")
                    and isinstance(output.get("text"), str) and output["text"].strip()):
                fetched.add(inputs["url"])
        elif row.tool_name == "analyze_images":
            for item in output.get("images", []):
                if item.get("artifact_id") in inputs.get("artifact_ids", []) and isinstance(item.get("analysis"), dict):
                    analyses[item["artifact_id"]] = item["analysis"]
        elif inputs.get("run_id") == run.run_id and output.get("reference_id"):
            downloads.append((inputs, output["reference_id"]))
    observations, admitted = [], []
    for hit in hits:
        if hit["kind"] == "web":
            if hit.get("url") in fetched:
                admitted.append(hit)
            continue
        for inputs, reference_id in downloads:
            if (inputs.get("image_url") == hit.get("image_url") and inputs.get("entity")
                    and inputs.get("source_page_url") in {None, hit.get("source_page_url")}
                    and reference_id in analyses):
                observations.append({"entity": inputs["entity"], "source_id": hit["result_id"], "reference_id": reference_id})
                admitted.append(hit)
    return validate_dossier(payload, {"run_id": run.run_id, "research_hits": admitted,
        "research_images": observations, "research_analyses": analyses, "research_warnings": []})


def _item(row, *, include_payload=True):
    result = {"key": row.key, "version": row.version, "kind": row.kind,
              "workspace_ref": {"key": row.key, "version": row.version},
              "author_agent": row.author_agent, "delegation_id": row.delegation_id,
              "artifact_ids": deepcopy(row.artifact_ids), "created_at": as_utc(row.created_at).isoformat()}
    if include_payload:
        result["payload"] = deepcopy(row.payload)
    else:
        result["summary"] = next((row.payload[name][:200] for name in ("summary", "title", "message", "text")
                                  if isinstance(row.payload.get(name), str)), row.kind)
    return result


def write_workspace(key, kind, payload, ctx):
    run, delegation = require_context(ctx)
    key = _key(key)
    value = validate_payload(kind, payload)
    request_key = ctx.idempotency_key
    if not isinstance(request_key, str) or not 1 <= len(request_key) <= 128:
        raise AppError("INVALID_AGENT_CONTEXT", "Workspace writes require a server idempotency key", 403)
    digest = sha256(json.dumps({"key": key, "kind": kind, "payload": value}, sort_keys=True,
                               ensure_ascii=False, allow_nan=False, separators=(",", ":")).encode("utf-8")).hexdigest()
    try:
        # Serializes version allocation and receipt admission across workers.
        run = _lock_run(run)
        delegation = AgentDelegation.query.populate_existing().filter_by(
            id=delegation.id, run_id=run.run_id, agent=ctx.caller_agent).with_for_update().one()
        previous = AgentWorkspaceItem.query.filter_by(run_id=run.run_id, request_key=request_key).first()
        if previous:
            if (previous.inputs_hash != digest or previous.delegation_id != delegation.id
                    or previous.author_agent != delegation.agent):
                raise AppError("IDEMPOTENCY_CONFLICT", "Workspace write key was used for another input", 409)
            result = _item(previous)
            db.session.commit()
            return result
        if (delegation.status in {"completed", "returned", "failed", "limit", "cancelled", "success"}
                or run.status in {"success", "partial_success", "failed", "cancelled"}):
            raise AppError("AGENT_DELEGATION_FINISHED", "Finished runs and delegations cannot append decisions", 409)
        if kind == "brief":
            if delegation.agent != "producer":
                raise AppError("TOOL_FORBIDDEN", "Only Producer can write the requirement brief", 403)
            _validate_brief(value, run)
        elif kind == "research_dossier":
            value = validate_payload(kind, _validate_research(value, run))
        elif kind == "patch":
            if delegation.agent not in {"repair", "director"}:
                raise AppError("TOOL_FORBIDDEN", "Only Repair and Director can write Patch drafts", 403)
            from app.plans.patch_tools import validate_evidence
            validate_evidence(value, ctx)
        ids = validate_artifact_references(value, ctx, plan_refs=kind in {"plan_draft", "patch"})
        latest = AgentWorkspaceItem.query.filter_by(run_id=run.run_id, key=key).order_by(
            AgentWorkspaceItem.version.desc()).first()
        if latest and latest.kind != kind:
            raise AppError("WORKSPACE_KIND_CONFLICT", "Workspace key cannot change kind between versions", 409)
        row = AgentWorkspaceItem(run_id=run.run_id, key=key, version=latest.version + 1 if latest else 1,
            kind=kind, payload=value, artifact_ids=ids, author_agent=delegation.agent, delegation_id=delegation.id,
            request_key=request_key, inputs_hash=digest)
        db.session.add(row)
        db.session.commit()
        return _item(row)
    except Exception:
        db.session.rollback()
        raise


def read_workspace(ctx, key=None, kind=None, version=None):
    run, _delegation = require_context(ctx)
    if kind is not None and kind not in WORKSPACE_KINDS:
        raise AppError("INVALID_WORKSPACE_KIND", "Unknown workspace kind", 422)
    if version is not None and (type(version) is not int or version < 1 or key is None):
        raise AppError("INVALID_WORKSPACE_REFERENCE", "An exact version requires a key and positive integer", 422)
    query = AgentWorkspaceItem.query.filter_by(run_id=run.run_id)
    if key is not None:
        query = query.filter_by(key=_key(key))
    if kind is not None:
        query = query.filter_by(kind=kind)
    if version is not None:
        query = query.filter_by(version=version)
    rows = query.order_by(AgentWorkspaceItem.key, AgentWorkspaceItem.version.desc()).all()
    latest = {}
    for row in rows:
        latest.setdefault(row.key, row)
    if key is not None and not latest:
        raise AppError("WORKSPACE_ITEM_NOT_FOUND", "Workspace item not found in this Run", 404)
    return {"items": [_item(row, include_payload=key is not None) for row in latest.values()]}


def resolve_workspace_ref(ref, ctx, expected_kind=None):
    try:
        value = WorkspaceRef.model_validate(ref)
    except ValidationError as error:
        raise AppError("INVALID_WORKSPACE_REFERENCE", "Expected an exact workspace key and version", 422) from error
    item = read_workspace(ctx, key=value.key, version=value.version)["items"][0]
    if expected_kind is not None and item["kind"] != expected_kind:
        raise AppError("WORKSPACE_KIND_MISMATCH", "Workspace reference has the wrong decision type", 422)
    return item
