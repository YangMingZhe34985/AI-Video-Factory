"""V8b: classic series/template catalog and template-target validation (V.25.1)."""

import pytest

from app.api import AppError
from app.extensions import db
from app.models import Series
from app.plans.workflow import catalog, created_template_id, resolve_target
from app.services.prompt_service import PromptService
from app.tools import build_v3_registry
from app.tools.job_backed import ensure_agent_template
from tests.test_v3_catalog_tools import context, make_run


def classic_template(name="雨夜街头", series="default"):
    template = PromptService.create_template({"name": name, "series": series, "description": "城市夜景系列"})
    PromptService.create_version_for_template(template, {"prompt_type": "t2v", "title": "t2v", "content": "雨夜霓虹街道，行人撑伞走过。" * 10,
                                                         "source": "manual", "activate": True})
    db.session.commit()
    return template


def test_catalog_lists_public_templates_with_prompt_previews(app_ctx):
    template = classic_template()
    ensure_agent_template()
    output = build_v3_registry().invoke("list_templates", {}, context(make_run()))["output"]
    series_ids = [item["series_id"] for item in output["series"]]
    assert "agent_studio" not in series_ids
    entries = [entry for item in output["series"] for entry in item["templates"]]
    assert all(entry["template_id"] != "agent_workspace" for entry in entries)
    entry = next(entry for entry in entries if entry["template_id"] == template.template_id)
    assert entry["prompt_types"]["t2v"]["preview"].startswith("雨夜霓虹街道")
    assert len(entry["prompt_types"]["t2v"]["preview"]) == 120


def test_catalog_filters_by_series_and_query(app_ctx):
    db.session.add(Series(series_id="ads", name="广告", description="广告系列", is_default=False))
    db.session.commit()
    classic_template("新品发布", series="ads")
    classic_template("雨夜街头")
    found = catalog(query="新品")
    assert [item["series_id"] for item in found] == ["ads"]
    assert [entry["name"] for entry in catalog(series_id="ads")[0]["templates"]] == ["新品发布"]
    with pytest.raises(AppError) as error:
        catalog(series_id="agent_studio")
    assert error.value.code == "SERIES_NOT_FOUND"


def test_target_resolution_rejects_internal_and_duplicate_targets(app_ctx):
    template = classic_template()
    ensure_agent_template()
    existing = resolve_target({"template_id": template.template_id}, "run_1", "workflow")
    assert existing["mode"] == "existing" and existing["series_id"] == "default"
    created = resolve_target({"series_id": "default", "new_template_name": " 新模板 "}, "run_1", "workflow")
    assert created == {"mode": "new", "template_id": created_template_id("run_1", "workflow"),
                       "template_name": "新模板", "series_id": "default", "series_name": created["series_name"]}
    cases = [({"template_id": "agent_workspace"}, "TEMPLATE_NOT_FOUND"),
             ({"series_id": "agent_studio", "new_template_name": "x"}, "SERIES_NOT_FOUND"),
             ({"series_id": "missing", "new_template_name": "x"}, "SERIES_NOT_FOUND"),
             ({"series_id": "default", "new_template_name": template.name}, "TEMPLATE_NAME_EXISTS"),
             ({"series_id": "default", "new_template_name": ""}, "INVALID_TEMPLATE_TARGET"),
             ({"template_id": template.template_id, "series_id": "default"}, "INVALID_TEMPLATE_TARGET")]
    for target, code in cases:
        with pytest.raises(AppError) as error:
            resolve_target(target, "run_1", "workflow")
        assert error.value.code == code, target


def test_producer_card_exposes_read_only_catalog(app_ctx):
    registry = build_v3_registry()
    schema = registry.function_schemas(["list_templates"])[0]["function"]
    assert set(schema["parameters"]["properties"]) == {"series_id", "query"}
    assert "list_templates" in app_ctx.extensions["agent_v3_cards"].cards["producer"].tools
