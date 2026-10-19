from types import SimpleNamespace

from scripts.v3_eval.metrics import delegation_tree, history_issues, plan_metrics, summarize_turns


def row(tool, output, **kwargs):
    return SimpleNamespace(tool_name=tool, output_payload=output, invocation_id="test", caller_agent="producer",
                           delegation_id=1, status="success", estimated_cost=1, error_code=None, **kwargs)


def test_metrics_keep_missing_usage_and_compiler_failures_visible():
    result = summarize_turns([
        row("agent_llm_turn", {"usage": {"prompt_tokens": 60001, "completion_tokens": 20}}),
        row("agent_llm_turn", {}),
        row("analyze_images", {"usage": {"prompt_tokens": 100, "completion_tokens": 10}}),
        row("check_plan", {"issues": [{"code": "PLAN_UNUSED_PAID_NODE", "node_id": "unused"}]}),
    ])
    assert result["llm"] == {"calls": 2, "input_tokens_max": 60001, "input_tokens_sum": 60001,
                             "output_tokens_sum": 20, "usage_missing": 1}
    assert result["vision"]["calls"] == 1
    assert result["compile_issue_codes"] == ["PLAN_UNUSED_PAID_NODE"]


def test_choice_reference_and_tree_distinguish_child_from_root():
    assert delegation_tree([SimpleNamespace(id=1, parent_id=None, agent="producer", status="completed", llm_calls=3),
                            SimpleNamespace(id=2, parent_id=1, agent="director", status="completed", llm_calls=5)])[0]["children"][0]["agent"] == "director"
    plan = {"nodes": [{"id": "choice", "tool": "select_image", "gate": "choice"},
                      {"id": "video", "tool": "animate_shot", "params": {"duration": 10},
                       "inputs": {"image_artifact_id": {"ref": "choice.image"}}}]}
    assert plan_metrics(plan)["animation_uses_selection"] is True
    assert plan_metrics(plan)["video_duration_total"] == 10
    plan["nodes"][1]["inputs"] = {"image_artifact_id": {"ref": "first.image"}}
    assert plan_metrics(plan)["animation_uses_selection"] is False


def test_free_check_plan_issues_are_read_from_canonical_history():
    result = history_issues([{"messages": [{"role": "tool", "name": "check_plan",
        "content": '{"issues":[{"code":"PLAN_UNUSED_PAID_NODE"}]}'},
        {"role": "tool", "name": "write_workspace", "content": '{"ok":false,"error":{"code":"INVALID_INPUT"}}'}]}])
    assert result["history_compile_issue_codes"] == ["PLAN_UNUSED_PAID_NODE"]
    assert result["tool_failures"][0]["tool"] == "write_workspace"
