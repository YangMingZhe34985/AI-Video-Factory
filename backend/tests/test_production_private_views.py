"""Public prompt/job listings cannot reveal another user's private story input."""
import pytest
from flask_jwt_extended import create_access_token

from app.extensions import db
from app.services.job_service import JobService
from app.services.prompt_service import PromptService
from app.skills.job_backed import ensure_agent_template, node_selection
from tests.test_story_previews import setup

pytestmark = pytest.mark.config(AGENT_MODE_ENABLED=True, AGENT_STORY_V2_ENABLED=True,
    AGENT_STORY_PRODUCTION_ENABLED=True, API_AUTH_REQUIRED=True,
    JWT_SECRET_KEY="private-views-test-key-longer-than-thirty-two")


def headers(owner):
    return {"Authorization": f"Bearer {create_access_token(identity=owner)}"}


def fixture(marker="agent_story_production"):
    template = ensure_agent_template()
    jobs = {}
    for owner in ("alice", "bob"):
        row, _version, _registry = setup(characters=False)
        row.owner_id = owner
        db.session.commit()
        config = {"skill": {"budget_scope": row.run_id}, marker: {"run_id": row.run_id}}
        strategy = "skill:fixture"
        if marker == "agent_upload":
            config = {"agent_upload_owner": owner}
            strategy = "agent_upload"
        jobs[owner] = JobService.create_job({"template_id": template.template_id,
            "strategy": strategy, **node_selection([]), "job_config": config,
            "initial_prompts": {"i2v": f"{owner}-private-motion"}})
    classic = JobService.create_job({"template_id": "default", "strategy": "manual",
        **node_selection([]), "initial_prompts": {"i2v": "classic-motion"}})
    # Represent a package-era historical sync, including after future writes stop.
    PromptService.create_version_for_template(template, {"prompt_type": "i2v",
        "title": "Historical sync", "content": "historical-other-user-private-motion"})
    db.session.commit()
    return template, jobs, classic


@pytest.mark.parametrize("marker", ["agent_story_production", "agent_story_preview", "agent_upload"])
def test_public_lists_filter_private_jobs_before_pagination_and_prompt_projection(app_ctx, client, marker):
    template, jobs, classic = fixture(marker)
    owner = headers("bob")
    response = client.get("/api/jobs?perPage=1", headers=owner)
    data = response.json["data"]
    assert response.status_code == 200
    assert data["total"] == 2 and sum(data["status_counts"].values()) == 2
    assert len(data["jobs"]) == 1
    visible = client.get("/api/jobs?perPage=100", headers=owner).json["data"]["jobs"]
    assert {item["job_id"] for item in visible} == {jobs["bob"].job_id, classic.job_id}
    assert "alice-private-motion" not in str(visible)

    response = client.get("/api/prompts", headers=owner)
    assert response.status_code == 200
    assert "alice-private-motion" not in response.get_data(as_text=True)
    assert "historical-other-user-private-motion" not in response.get_data(as_text=True)
    assert "bob-private-motion" in response.get_data(as_text=True)
    assert "classic-motion" in response.get_data(as_text=True)
    response = client.get(f"/api/prompts?job_id={jobs['alice'].job_id}", headers=owner)
    assert response.status_code == 404

    response = client.get(f"/api/templates/{template.template_id}/jobs/{jobs['bob'].job_id}/prompts", headers=owner)
    assert response.status_code == 200
    assert "bob-private-motion" in response.get_data(as_text=True)
    assert "historical-other-user-private-motion" not in response.get_data(as_text=True)


@pytest.mark.parametrize("suffix", [
    "/prompts/i2v/active?job_id={job}", "/prompts/i2v/versions?job_id={job}",
    "/jobs/{job}/prompts", "/jobs/{job}/prompts/i2v",
    "/jobs/{job}/prompts/i2v/default/active", "/jobs/{job}/prompts/i2v/default/versions",
])
def test_all_explicit_job_prompt_reads_require_owner(app_ctx, client, suffix):
    template, jobs, _classic = fixture()
    path = "/api/templates/" + template.template_id + suffix.format(job=jobs["alice"].job_id)
    assert client.get(path, headers=headers("bob")).status_code == 404
    own = client.get(path, headers=headers("alice"))
    assert own.status_code == 200
    assert "alice-private-motion" in own.get_data(as_text=True)
    assert client.get(path).status_code == 401


def test_internal_template_history_cannot_be_read_or_rewritten_through_aliases(app_ctx, client):
    template, jobs, _classic = fixture()
    owner = headers("bob")
    for template_id in (template.template_id, str(template.id)):
        prefix = f"/api/templates/{template_id}/prompts"
        for suffix in ("", "/i2v/active", "/i2v/versions"):
            # GET handlers ignore a JSON job_id, so it cannot authorize the template view.
            result = client.get(prefix + suffix, headers=owner, json={"job_id": jobs["bob"].job_id})
            assert result.status_code == 404
        assert client.post(prefix + "/seed-factory", headers=owner,
            json={"job_id": jobs["bob"].job_id}).status_code == 404
        assert client.post(prefix + "/i2v/activate?job_id=" + jobs["bob"].job_id,
            headers=owner, json={"version": "v1.0"}).status_code == 404
    response = client.post(f"/api/templates/{template.template_id}/prompts/i2v/versions/v1.0/edit",
        headers=owner, json={"job_id": jobs["alice"].job_id, "content": "replacement"})
    assert response.status_code == 404
    assert client.get("/api/templates/default/prompts/i2v/active", headers=owner).status_code == 200
