"""Versioned budget-scope policy lookup preserves legacy recovery semantics."""

from app.agent import model_policy
from app.extensions import db
from app.models import AgentRun


def test_v2_understanding_does_not_parse_legacy_goal(app_ctx, monkeypatch):
    def no_legacy(*_args, **_kwargs):
        raise AssertionError("v2 must not extract model constraints from legacy text")

    monkeypatch.setattr(model_policy, "build_policy", no_legacy)
    row = AgentRun(owner_id="local", request_key="v2", request={"schema_version": 2, "text": "生成猫的视频"})
    db.session.add(row)
    db.session.commit()
    assert model_policy.request_policy(row.request) is None
    assert model_policy.scope_policy(row.run_id) is None
    frozen = {"source": "server_default", "defaults": {"i2v": "frozen-model"},
              "requested": [], "excluded": [], "allowed_model_ids": []}
    row.snapshot = {"video_model_policy": frozen}
    db.session.commit()
    assert model_policy.scope_policy(row.run_id) == frozen


def test_v1_scope_keeps_saved_policy_and_legacy_extraction(app_ctx):
    policy = model_policy.build_policy("生成猫的视频，使用 wan2.7 系列")
    row = AgentRun(owner_id="local", request_key="v1", request={"goal": "生成猫的视频，使用 wan2.7 系列"})
    db.session.add(row)
    db.session.commit()
    assert model_policy.scope_policy(row.run_id) == policy
    row.request = {**row.request, "goal": "已编辑但历史策略不可漂移", "video_model_policy": policy}
    db.session.commit()
    assert model_policy.scope_policy(row.run_id) == policy
