"""Server-owned Run scope, ledger limits and provenance-based URL allowlists."""

import re

from flask import current_app, has_request_context
from flask_jwt_extended import get_jwt_identity

from app.api import AppError
from app.models import AgentRun, ToolInvocation


def require_run(ctx, run_id=None):
    if run_id is not None and run_id != ctx.budget_scope:
        raise AppError("TOOL_FORBIDDEN", "Research input and budget scope belong to different runs", 403)
    run = AgentRun.query.filter_by(run_id=ctx.budget_scope).first()
    if run is None:
        raise AppError("AGENT_RUN_NOT_FOUND", "Research requires an existing Agent run", 404)
    if has_request_context():
        owner = get_jwt_identity() if current_app.config.get("API_AUTH_REQUIRED", True) else "local"
        if run.owner_id != owner:
            raise AppError("AGENT_RUN_NOT_FOUND", "Agent run not found", 404)
    limit = run.request["budget_limit"]
    ctx.budget_limit = min(limit, ctx.budget_limit) if ctx.budget_limit is not None else limit
    return run


RUN_BOUND_TOOLS = frozenset({"fetch_page", "download_reference", "capture_reference_page"})


def bind_run_input(tool_name, data, ctx):
    """Canonicalize optional legacy Run fields before ledger identity/replay."""
    if tool_name not in RUN_BOUND_TOOLS or "run_id" not in type(data).model_fields:
        return data
    run = require_run(ctx, data.run_id)
    return data.model_copy(update={"run_id": run.run_id})


def reserve(ctx, tool_names, limit_config):
    """The pending ledger row reserves a slot; failures keep their consumed slot."""
    run = require_run(ctx)
    used = ToolInvocation.query.filter(ToolInvocation.budget_scope == run.run_id,
        ToolInvocation.tool_name.in_(tool_names), ToolInvocation.status != "rejected").count()
    if used > current_app.config[limit_config]:
        raise AppError("RESEARCH_LIMIT_REACHED", "This run reached its research operation limit", 409)


def allowed_urls(run_id):
    run = AgentRun.query.filter_by(run_id=run_id).first()
    if run is None:
        return set()
    urls = {value.rstrip(".,;!?，。；！？）)}") for value in re.findall(r"https?://[^\s<>\"'（(]+", run.request.get("text", ""))}
    rows = ToolInvocation.query.filter(ToolInvocation.budget_scope == run_id,
        ToolInvocation.tool_name.in_(["web_search", "image_search"]),
        ToolInvocation.status.in_(["success", "partial_success"])).all()
    for row in rows:
        for result in (row.output_payload or {}).get("results", []):
            for field in ("url", "image_url", "thumbnail_url", "source_page_url"):
                if isinstance(result.get(field), str):
                    urls.add(result[field])
    return urls


def require_allowed_url(url, ctx, run_id=None):
    run = require_run(ctx, run_id)
    if url not in allowed_urls(run.run_id):
        raise AppError("URL_NOT_ALLOWED", "URL did not originate in this run's search results or user text", 422)
    return run
