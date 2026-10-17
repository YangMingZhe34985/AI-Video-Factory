"""B1 contracts: Run-scoped search, provenance, limits and recovery."""

import pytest
from pydantic import BaseModel, ValidationError

from app.agent.recovery import invoke_once
from app.agent.search import get_search_provider
from app.agent.search.base import ImageResult, WebResult
from app.agent.search.fetch import fetch_resource
from app.agent.search.scope import allowed_urls
from app.api import AppError
from app.extensions import db
from app.models import AgentRun, ToolInvocation
from app.skills import build_default_registry
from app.skills.budget import BudgetGuard
from app.skills.registry import ToolRegistry
from app.skills.spec import ToolContext, ToolSpec
from app.utils.ids import new_id


def research_run(text="请查找 AI 漫化形象", owner="local", budget=10):
    run = AgentRun(owner_id=owner, request_key=new_id("test"), request={"schema_version": 2,
        "text": text, "attachment_ids": [], "budget_limit": budget})
    db.session.add(run)
    db.session.commit()
    return run


def ctx(run, key=None):
    return ToolContext(role="research", budget_scope=run.run_id, idempotency_key=key)


def test_mock_search_is_forced_and_replay_is_scoped(app_ctx):
    app_ctx.config["AGENT_SEARCH_PROVIDER"] = "unconfigured"
    assert get_search_provider().name == "mock"
    registry = build_default_registry()
    first, second = research_run(), research_run()
    one = registry.invoke("web_search", {"query": "AI 漫化"}, ctx(first))
    replay = registry.invoke("web_search", {"query": "AI 漫化"}, ctx(first))
    other = registry.invoke("web_search", {"query": "AI 漫化"}, ctx(second))
    assert replay["replayed"] and replay["invocation_id"] == one["invocation_id"]
    assert other["invocation_id"] != one["invocation_id"]
    assert BudgetGuard.spent(first.run_id) == pytest.approx(0.2)
    assert all(row.budget_scope in row.idempotency_key for row in ToolInvocation.query.all())


def test_existing_run_server_budget_and_roles_are_required_before_call(app_ctx):
    registry = build_default_registry()
    for scope, role in [("missing", "research"), ("default", "system")]:
        with pytest.raises(AppError) as stopped:
            registry.invoke("web_search", {"query": "x"}, ToolContext(role=role, budget_scope=scope))
        assert stopped.value.code == "AGENT_RUN_NOT_FOUND"
    low = research_run(budget=0.1)
    with pytest.raises(AppError) as stopped:
        registry.invoke("web_search", {"query": "x"}, ToolContext(role="research", budget_scope=low.run_id, budget_limit=1000))
    assert stopped.value.code == "BUDGET_EXCEEDED"
    with pytest.raises(AppError) as stopped:
        registry.invoke("web_search", {"query": "x"}, ToolContext(role="director", budget_scope=low.run_id))
    assert stopped.value.code == "TOOL_FORBIDDEN"


def test_success_replay_rejects_different_run_or_input(app_ctx):
    registry = build_default_registry()
    one, two = research_run(), research_run()
    key = f"{one.run_id}:query"
    registry.invoke("web_search", {"query": "cat"}, ctx(one, key))
    for run, data in [(two, {"query": "cat"}), (one, {"query": "dog"})]:
        with pytest.raises(AppError) as stopped:
            invoke_once(registry, "web_search", data, ctx(run, key))
        assert stopped.value.code == "IDEMPOTENCY_KEY_CONFLICT"
    assert ToolInvocation.query.count() == 1


def test_url_allowlist_uses_only_own_successful_searches_and_user_text(app_ctx):
    one, two = research_run("查阅 https://public.example/facts。"), research_run()
    registry = build_default_registry()
    result = registry.invoke("web_search", {"query": "cat"}, ctx(one))["output"]
    url = result["results"][0]["url"]
    assert url in allowed_urls(one.run_id) and url not in allowed_urls(two.run_id)
    assert "https://public.example/facts" in allowed_urls(one.run_id)
    one.snapshot = {"research_urls": ["mock://page/chatgpt"]}
    db.session.commit()
    with pytest.raises(AppError) as stopped:
        fetch_resource(url, ctx(two), max_bytes=10000, allowed_types={"text/html"})
    assert stopped.value.code == "URL_NOT_ALLOWED"
    invocation = ToolInvocation.query.one()
    invocation.status = "failed"
    db.session.commit()
    assert url not in allowed_urls(one.run_id)


def test_mock_never_issues_dns_or_http_even_for_user_allowlisted_urls(app_ctx, monkeypatch):
    from app.agent.search import fetch
    run = research_run("读取 https://public.example/facts")
    monkeypatch.setattr(fetch.socket, "getaddrinfo", lambda *a, **k: pytest.fail("Mock must not perform DNS"))
    with pytest.raises(AppError) as stopped:
        fetch_resource("https://public.example/facts", ctx(run), max_bytes=10000, allowed_types={"text/html"})
    assert stopped.value.code == "URL_NOT_ALLOWED"
    with pytest.raises(AppError):
        fetch_resource("mock://page/injection", ctx(run), max_bytes=10000, allowed_types={"text/html"})


def test_fetch_strips_script_and_style_but_preserves_untrusted_prose(app_ctx):
    run = research_run()
    registry = build_default_registry()
    result = registry.invoke("web_search", {"query": "injection"}, ctx(run))["output"]
    page = registry.invoke("fetch_page", {"run_id": run.run_id, "url": result["results"][0]["url"]}, ctx(run))["output"]
    assert "忽略之前的指令" in page["text"]
    assert "discard_me" not in page["text"] and "display:none" not in page["text"]
    assert BudgetGuard.spent(run.run_id) == pytest.approx(0.2)
    assert len(page["text"]) <= 8000


def test_search_failures_consume_one_slot_and_do_not_retry_paid_calls(app_ctx, monkeypatch):
    from app.agent.search.providers.mock import MockSearchProvider
    run = research_run()
    registry = build_default_registry()
    app_ctx.config["AGENT_RESEARCH_MAX_QUERIES"] = 1
    calls = []
    def fail(*a, **k):
        calls.append(1)
        raise RuntimeError("injected provider failure")
    monkeypatch.setattr(MockSearchProvider, "web_search", fail)
    with pytest.raises(AppError) as stopped:
        registry.invoke("web_search", {"query": "one"}, ctx(run))
    assert stopped.value.code == "SEARCH_PROVIDER_UNAVAILABLE"
    with pytest.raises(AppError) as stopped:
        registry.invoke("web_search", {"query": "two"}, ctx(run))
    assert stopped.value.code == "RESEARCH_LIMIT_REACHED"
    with pytest.raises(AppError):
        registry.invoke("web_search", {"query": "one"}, ctx(run))
    assert calls == [1]
    assert BudgetGuard.spent(run.run_id) == pytest.approx(0.2)


def test_fetch_limits_count_invocations_but_not_successful_replay(app_ctx):
    run = research_run()
    registry = build_default_registry()
    urls = [item["url"] for item in registry.invoke("web_search", {"query": "all"}, ctx(run))["output"]["results"]]
    app_ctx.config["AGENT_RESEARCH_MAX_FETCHES"] = 1
    data = {"run_id": run.run_id, "url": urls[0]}
    first = registry.invoke("fetch_page", data, ctx(run))
    assert registry.invoke("fetch_page", data, ctx(run))["invocation_id"] == first["invocation_id"]
    with pytest.raises(AppError) as stopped:
        registry.invoke("fetch_page", {"run_id": run.run_id, "url": urls[1]}, ctx(run))
    assert stopped.value.code == "RESEARCH_LIMIT_REACHED"


@pytest.mark.parametrize("bad", ["javascript:alert(1)", "file:///etc/passwd", "data:text/html,evil", "https://user:pass@example.com"])
def test_search_result_urls_are_safe_for_links_before_fetch(app_ctx, bad):
    with pytest.raises(ValidationError):
        WebResult(result_id="w1", rank=1, title="bad", url=bad, site="bad", snippet="bad")
    with pytest.raises(ValidationError):
        ImageResult(result_id="i1", rank=1, title="bad", image_url="mock://image/deepseek-1", source_page_url=bad)


def test_mock_image_fixture_has_two_entities_and_three_candidates_each(app_ctx):
    provider = get_search_provider()
    results = provider.image_search("AI 漫化 DeepSeek GPT", max_results=12, safe=True)
    assert len(results) == 6
    assert len({item.image_url for item in results}) == 6


def test_only_download_reference_can_recover_unknown_free_local_work(app_ctx):
    class Payload(BaseModel):
        value: str
    calls = []
    registry = ToolRegistry()
    for name in ("download_reference", "web_search", "fetch_page"):
        registry.register(ToolSpec(name=name, description="fixture", input_model=Payload, output_model=Payload,
            handler=lambda data, context: calls.append(context.tool_name) or data, permission="external",
            allowed_roles=frozenset({"research"}), max_retries=0))
    run = research_run()
    for name in registry.names():
        key = f"{run.run_id}:{name}"
        db.session.add(ToolInvocation(tool_name=name, idempotency_key=key, caller_role="research",
            budget_scope=run.run_id, status="pending", input_payload={"value": "saved"}, estimated_cost=0))
        db.session.commit()
        if name == "download_reference":
            assert invoke_once(registry, name, {"value": "saved"}, ctx(run, key))["output"] == {"value": "saved"}
        else:
            with pytest.raises(AppError) as stopped:
                invoke_once(registry, name, {"value": "saved"}, ctx(run, key))
            assert stopped.value.code == "RECOVERY_REQUIRED"
    assert calls == ["download_reference"]


def test_input_run_cannot_borrow_another_run_allowlist(app_ctx):
    one, two = research_run(), research_run()
    with pytest.raises(AppError) as stopped:
        build_default_registry().invoke("fetch_page", {"run_id": two.run_id, "url": "mock://page/deepseek"}, ctx(one))
    assert stopped.value.code == "TOOL_FORBIDDEN"
    assert ToolInvocation.query.count() == 0


def test_integrity_conflict_path_revalidates_existing_external_scope(app_ctx, monkeypatch):
    registry = build_default_registry()
    one, two = research_run(), research_run()
    original = registry._check_budget
    key = f"{one.run_id}:race"
    def concurrent(invocation, context, cost, record_new=False):
        original(invocation, context, cost, record_new)
        db.session.add(ToolInvocation(tool_name="web_search", idempotency_key=key, caller_role="research",
            budget_scope=two.run_id, input_payload=invocation.input_payload, estimated_cost=0.2,
            status="success", output_payload={"query": "secret", "results": []}))
        db.session.commit()
    monkeypatch.setattr(registry, "_check_budget", concurrent)
    with pytest.raises(AppError) as stopped:
        registry.invoke("web_search", {"query": "cat"}, ctx(one, key))
    assert stopped.value.code == "IDEMPOTENCY_KEY_CONFLICT"


def test_completed_structured_response_error_keeps_billable_ledger(app_ctx):
    class Payload(BaseModel):
        value: str
    def invalid_response(_data, _ctx):
        raise AppError("INVALID_RESEARCH_DOSSIER", "Completed response did not match schema", 422,
                       payload={"response_validation": True})
    registry = ToolRegistry()
    registry.register(ToolSpec(name="research_schema", description="fixture", input_model=Payload,
        output_model=Payload, handler=invalid_response, permission="llm", allowed_roles=frozenset({"research"}),
        max_retries=0, cost_fn=lambda _data, _ctx: 1))
    run = research_run()
    with pytest.raises(AppError) as stopped:
        registry.invoke("research_schema", {"value": "x"}, ctx(run))
    assert stopped.value.code == "INVALID_RESEARCH_DOSSIER"
    assert ToolInvocation.query.one().status == "failed"
    assert BudgetGuard.spent(run.run_id) == 1
