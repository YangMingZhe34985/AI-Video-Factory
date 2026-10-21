"""Final-candidate assessments retain original evidence and conservative gates."""
from copy import deepcopy
import pytest

from app.agents import repair_flow
from app.extensions import db
from app.models import AgentWorkspaceItem
from app.plans import patches
from app.plans.views import public_patches
from tests.test_v5_repair_flow import assigned, failure, invoke

pytestmark = pytest.mark.config(AGENT_MODE_ENABLED=True, AGENT_V3_ENABLED=True)


@pytest.mark.parametrize("preserved", [True, False])
def test_revised_final_draft_reason_not_repair_proposal_is_bound_and_shown(app_ctx, preserved):
    run, _root, task, registry = failure(category="content_policy", allowance=20)
    run.request = {**run.request, "text": "生成一张猫跳舞的照片"}
    db.session.commit()
    repair = assigned(run, registry)
    proposal = {"base_version": task.plan_version, "reason": "原提议把跳舞改成自然摆动",
                "evidence_refs": [{"task_id": task.id}], "ops": [{"op": "update_inputs", "node_id": "image",
                "inputs": {"prompt": "An orange cat sways naturally"}}]}
    result = invoke(run, repair, registry, "propose_patch", {"draft": proposal}, "weak-motion")
    assert repair_flow.advance_repair_flow(run, registry)
    director = repair_flow.planning_delegation(run)
    assert "For verdict=revise, assess revised_draft" in director.task
    assert "reason, intent_preserved and changed_elements" in director.task
    assert "keep intent_preserved=false" in director.task
    final = deepcopy(proposal)
    final["reason"] = "最终候选恢复用户要求的猫跳舞"
    final["ops"][0]["inputs"]["prompt"] = "An orange cat dancing rhythmically under warm light"
    reason = "最终候选明确保留猫跳舞及暖光背景" if preserved else "最终候选恢复了跳舞文字，但动作语义仍无法确认，需人工审核"
    invoke(run, director, registry, "review_patch", {"patch_id": result["patch_id"], "verdict": "revise",
           "reason": reason, "revised_draft": final, "intent_preserved": preserved, "changed_elements": []}, "final-review")
    record = run.snapshot["v3_patches"][result["patch_id"]]
    old = AgentWorkspaceItem.query.filter_by(run_id=run.run_id, key=record["proposal_ref"]["key"],
                                           version=record["proposal_ref"]["version"]).one()
    assert "sways naturally" in old.payload["ops"][0]["inputs"]["prompt"]
    assert record["draft"]["ops"][0]["inputs"]["prompt"] == final["ops"][0]["inputs"]["prompt"]
    view = public_patches(run)[0]
    assert view["review"]["reason"] == reason
    assert view["review"]["intent_preserved"] is preserved and view["review"]["changed_elements"] == []
    quote = patches.quote_patch(run, record, registry=registry)["quote"]
    assert quote["automatic"]["eligible"] is preserved
    assert ("PATCH_INTENT_UNCERTAIN" in quote["automatic"]["reasons"]) is (not preserved)
    assert "PATCH_INTENT_CHANGED" not in quote["automatic"]["reasons"]
