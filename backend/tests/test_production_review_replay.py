"""Approval intents must recheck current evidence after a process restart."""

import pytest

from app.agent import production_actions as actions
from app.agent.production_state import latest_tasks, usable_artifact
from app.api import AppError
from app.services.storage_service import StorageService
from app.skills.budget import BudgetGuard
from tests.test_production_actions import fixture

pytestmark = pytest.mark.config(AGENT_MODE_ENABLED=True, AGENT_STORY_V2_ENABLED=True,
    AGENT_STORY_PRODUCTION_ENABLED=True, AGENT_MAX_SHOT_AUTO_REPAIRS=0)


@pytest.mark.parametrize("target_type,code", [
    ("video", "VIDEO_INCOMPLETE"),
    ("keyframe", "PREVIEW_INCOMPLETE"),
])
def test_restarted_approval_rechecks_files_after_durable_intent(app_ctx, monkeypatch, target_type, code):
    row, version, registry = fixture()
    command = {"action": "approve_videos", "plan_version": version.version, "request_key": "approve"}
    save = actions._save_receipt

    def crash_after_intent(*args, **kwargs):
        result = save(*args, **kwargs)
        if kwargs.get("status") == "applying":
            raise RuntimeError("Injected crash after approval intent")
        return result

    monkeypatch.setattr(actions, "_save_receipt", crash_after_intent)
    with pytest.raises(RuntimeError):
        actions.apply_command(row, command, registry)
    assert row.snapshot["production_action_receipts"]["approve"]["status"] == "applying"
    artifact = usable_artifact(latest_tasks(row, version, target_type)["s01"])
    StorageService.resolve(artifact.file_path).unlink()
    spent = BudgetGuard.spent(row.run_id)
    monkeypatch.setattr(actions, "_save_receipt", save)

    with pytest.raises(AppError) as error:
        actions.apply_command(row, command, registry)
    assert error.value.code == code
    assert row.snapshot["production"]["status"] == "awaiting_video_review"
    assert BudgetGuard.spent(row.run_id) == spent
