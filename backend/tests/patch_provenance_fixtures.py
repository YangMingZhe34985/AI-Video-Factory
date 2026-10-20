"""Produce authentic free-tool provenance for controlled Patch test fixtures."""
from copy import deepcopy
from unittest.mock import patch

from app.extensions import db
from app.models import AgentDelegation
from app.tools import build_v3_registry
from app.tools.spec import ToolContext


def add_proposal_evidence(run, record, *, author="director"):
    """Persist the proposal through ToolRegistry, then restore test execution state."""
    patch_id, draft = record["patch_id"], deepcopy(record["draft"])
    snapshot, status = deepcopy(run.snapshot or {}), run.status
    writer = AgentDelegation(run_id=run.run_id, agent=author, task="Controlled Mock Patch author",
        request_key=patch_id + ":fixture-author", credits_limit=2, status="running")
    db.session.add(writer)
    db.session.flush()
    flow_id = patch_id + ":fixture-flow"
    flow = {"flow_id": flow_id, "base_version": draft["base_version"], "stage": "author_running",
        "author_role": author, "author_delegation_id": writer.id, "review_delegation_id": None,
        "trigger": deepcopy(record["trigger"]), "return_status": status, "patch_id": None}
    run.snapshot = {**snapshot, "v3_active_repair_flow": flow_id,
        "v3_repair_flows": {**snapshot.get("v3_repair_flows", {}), flow_id: flow}}
    run.status = "understanding"
    db.session.commit()
    context = ToolContext(role=author, caller_agent=author, delegation_id=writer.id,
        budget_scope=run.run_id, budget_limit=run.request["budget_limit"],
        idempotency_key=patch_id + ":fixture-propose")
    try:
        # Only the ID is deterministic; the production handler creates all proof.
        with patch("app.plans.patch_tools.new_id", return_value=patch_id):
            output = build_v3_registry().invoke("propose_patch", {"draft": draft}, context)["output"]
        actual = deepcopy(run.snapshot["v3_patches"][output["patch_id"]])
        receipts = deepcopy(run.snapshot["v3_patch_tool_receipts"])
        for field in ("author_delegation_id", "proposal_ref", "proposed_by"):
            record[field] = actual[field]
        snapshot["v3_patch_tool_receipts"] = receipts
    finally:
        run.snapshot, run.status = snapshot, status
        db.session.commit()
    return record
