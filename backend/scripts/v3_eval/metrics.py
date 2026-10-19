"""Read-only evaluation metrics; provider usage is never inferred from text length."""
import json


def issue_codes(value):
    found = set()
    if isinstance(value, dict):
        if isinstance(value.get("code"), str):
            found.add(value["code"])
        for child in value.values():
            found.update(issue_codes(child))
    elif isinstance(value, list):
        for child in value:
            found.update(issue_codes(child))
    return sorted(found)


def summarize_turns(ledger):
    turns, vision, compile_codes = [], [], set()
    for row in ledger:
        output = row.output_payload or {}
        if row.tool_name in {"agent_llm_turn", "analyze_images"}:
            usage = output.get("usage") or {}
            item = {"invocation_id": row.invocation_id, "agent": row.caller_agent,
                    "delegation_id": row.delegation_id, "status": row.status,
                    "prompt_tokens": usage.get("prompt_tokens"),
                    "completion_tokens": usage.get("completion_tokens"),
                    "credits": row.estimated_cost, "error_code": row.error_code}
            (turns if row.tool_name == "agent_llm_turn" else vision).append(item)
        if row.tool_name in {"check_plan", "submit_plan", "instantiate_blueprint", "propose_patch", "review_patch"}:
            compile_codes.update(issue_codes(output.get("issues", [])))
            if row.error_code:
                compile_codes.add(row.error_code)
    def usage(items):
        inputs = [r["prompt_tokens"] for r in items if isinstance(r["prompt_tokens"], int)]
        outputs = [r["completion_tokens"] for r in items if isinstance(r["completion_tokens"], int)]
        return {"calls": len(items), "input_tokens_max": max(inputs, default=0),
                "input_tokens_sum": sum(inputs), "output_tokens_sum": sum(outputs),
                "usage_missing": sum(r["prompt_tokens"] is None for r in items)}
    return {"llm": usage(turns), "vision": usage(vision), "turns": turns,
            "vision_calls": vision, "compile_issue_codes": sorted(compile_codes)}


def delegation_tree(delegations):
    items = {row.id: {"id": row.id, "agent": row.agent, "status": row.status,
                      "llm_calls": row.llm_calls, "children": []} for row in delegations}
    roots = []
    for row in delegations:
        if row.parent_id in items:
            items[row.parent_id]["children"].append(items[row.id])
        else:
            roots.append(items[row.id])
    return roots


def history_issues(states):
    """Free read tools have no ledger; inspect their canonical persisted receipts."""
    codes, failures = set(), []
    for state in states:
        for message in state.get("messages", []):
            if message.get("role") != "tool":
                continue
            try:
                receipt = json.loads(message.get("content") or "{}")
            except (TypeError, ValueError):
                continue
            name = message.get("name")
            if name in {"check_plan", "instantiate_blueprint", "submit_plan", "propose_patch", "review_patch"}:
                codes.update(issue_codes(receipt))
            if isinstance(receipt, dict) and (receipt.get("error") or receipt.get("ok") is False):
                failures.append({"tool": name, "call_id": message.get("tool_call_id"), "receipt": receipt})
    return {"history_compile_issue_codes": sorted(codes), "tool_failures": failures}


def plan_metrics(plan):
    nodes = plan.get("nodes", [])
    choices = [n for n in nodes if n.get("tool") == "select_image"]
    selectors = {n["id"] for n in choices}
    def selector_refs(value):
        if isinstance(value, dict):
            return (str(value.get("ref", "")).split(".")[0] in selectors
                    or any(selector_refs(v) for v in value.values()))
        return isinstance(value, list) and any(selector_refs(v) for v in value)
    return {"node_count": len(nodes), "choice_count": len(choices),
            "choice_gate_count": sum(n.get("gate") == "choice" for n in nodes),
            "choice_nodes": choices,
            "animation_uses_selection": any(selector_refs(n.get("inputs", {})) for n in nodes
                                             if n.get("tool") in {"animate_shot", "generate_video"}),
            "video_duration_total": sum((n.get("params") or {}).get("duration", 0) or 0 for n in nodes
                                        if n.get("tool") in {"animate_shot", "generate_video", "transform_video"})}
