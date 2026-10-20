"""Derive Patch authors from server-assigned immutable writing receipts."""
from copy import deepcopy

from app.agent.plan_versions import inputs_hash
from app.api import AppError
from app.extensions import db
from app.models import AgentDelegation, AgentWorkspaceItem


def changed_targets(draft):
    direct = {op["node"]["id"] if op["op"] == "insert_node" else op["node_id"] for op in draft["ops"]}
    incidental = {op["before"] for op in draft["ops"] if op["op"] == "insert_node" and op.get("before")} - direct
    return direct, incidental


def normalize_authors(nodes, draft, trusted_author):
    if trusted_author not in {"repair", "director"}:
        raise ValueError("Patch authors must come from verified server delegations")
    direct, incidental = changed_targets(draft)
    for node_id in direct | incidental:
        if node_id in nodes:
            nodes[node_id]["origin"] = {**nodes[node_id]["origin"], "agent": trusted_author}


def _row(run, ref, key, delegation_id, agent, name, payload):
    if (not isinstance(ref, dict) or set(ref) != {"key", "version"}
            or ref["key"] != key or type(ref["version"]) is not int or ref["version"] != 1
            or type(delegation_id) is not int):
        raise ValueError("Invalid Patch writer reference")
    delegation = db.session.get(AgentDelegation, delegation_id)
    row = AgentWorkspaceItem.query.filter_by(run_id=run.run_id, key=key, version=1).first()
    if (delegation is None or delegation.run_id != run.run_id or delegation.agent != agent
            or agent not in {"repair", "director"} or row is None or row.kind != "patch"
            or row.delegation_id != delegation_id or row.author_agent != agent
            or row.inputs_hash != inputs_hash({"key": key, "kind": "patch", "payload": row.payload})):
        raise ValueError("Patch writer does not match its immutable workspace")
    receipt = (run.snapshot or {}).get("v3_patch_tool_receipts", {}).get(row.request_key) or {}
    expected_input = payload(row.payload)
    if (receipt.get("name") != name or receipt.get("agent") != agent
            or receipt.get("delegation_id") != delegation_id
            or receipt.get("input_hash") != inputs_hash(expected_input)):
        raise ValueError("Patch writer lacks its original server tool receipt")
    return row, receipt


def verified_patch_author(run, record, draft):
    """Legacy records have unknown authors; partial/mismatched evidence is invalid."""
    markers = {"author_delegation_id", "proposal_ref"}
    if not markers.intersection(record):
        return None
    try:
        if not markers.issubset(record):
            raise ValueError("Incomplete Patch author evidence")
        delegation_id = record["author_delegation_id"]
        delegation = db.session.get(AgentDelegation, delegation_id) if type(delegation_id) is int else None
        if delegation is None:
            raise ValueError("Unknown proposal author")
        patch_id = record["patch_id"]
        proposal, receipt = _row(run, record["proposal_ref"], f"patch.{patch_id}.proposal",
            delegation_id, delegation.agent, "propose_patch", lambda value: {"draft": value})
        if (record.get("proposed_by") != delegation.agent
                or receipt.get("output", {}).get("patch_id") != patch_id
                or receipt.get("output", {}).get("patch_ref") != record["proposal_ref"]):
            raise ValueError("Proposal provenance was changed")
        review = record.get("director_review") or {}
        writer, source = proposal, "proposal"
        if review.get("verdict") == "revise":
            fields = {key: deepcopy(review[key]) for key in ("verdict", "reason")}
            for key in ("intent_preserved", "changed_elements"):
                if key in review:
                    fields[key] = deepcopy(review[key])
            fields["patch_id"] = patch_id
            writer, receipt = _row(run, review.get("review_ref"), f"patch.{patch_id}.review",
                record.get("review_delegation_id"), "director", "review_patch",
                lambda value: {**fields, "revised_draft": value})
            if (writer.delegation_id == proposal.delegation_id
                    or review.get("delegation_id") != writer.delegation_id
                    or review.get("request_key") != writer.request_key
                    or receipt.get("output", {}).get("review_ref") != review["review_ref"]):
                raise ValueError("Revised draft lacks its independently assigned author")
            source = "director_revision"
        if writer.payload != draft:
            raise ValueError("Final Patch differs from its actual author's immutable draft")
        return {"agent": writer.author_agent, "delegation_id": writer.delegation_id,
            "proposed_by": proposal.author_agent, "source": source,
            "writer_ref": {"key": writer.key, "version": writer.version},
            "request_key": writer.request_key, "payload_hash": inputs_hash(writer.payload)}
    except (KeyError, TypeError, ValueError) as error:
        raise AppError("PATCH_AUTHOR_REQUIRED", "Patch author lacks matching immutable writer evidence", 403) from error


def metadata_changes(before, after, draft):
    old = {node["id"]: node for node in before.get("nodes", [])}
    new = {node["id"]: node for node in after.get("nodes", [])}
    direct, incidental = changed_targets(draft)
    changes = []
    for node_id in sorted(direct | incidental):
        original, current = old.get(node_id, {}), new.get(node_id, {})
        fields = {key: {"before": deepcopy(original.get(key)), "after": deepcopy(current.get(key))}
            for key in ("origin", "rationale", "depends_on") if original.get(key) != current.get(key)}
        if fields:
            changes.append({"node_id": node_id, "incidental": node_id in incidental, **fields})
    return changes
