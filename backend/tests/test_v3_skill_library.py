"""Repository Skill validation and read-only Registry boundaries; no model calls."""

import logging
from pathlib import Path
import sys
from types import ModuleType

import pytest
import yaml

from app.agents.skill_library import (
    EXTENSION_KEY, SkillLibrary, SkillLibraryError, get_skill_library, initialize_skill_library,
)
from app.api import AppError
from app.extensions import db
from app.models import AgentRun, ToolInvocation
from app.tools import build_default_registry, build_v3_registry
from app.tools.spec import ToolContext
from app.tools.specs.skill_library import register_skill_tools
from app.utils.ids import new_id


def registry():
    result = build_v3_registry()
    if "list_skills" not in result.names():
        register_skill_tools(result)
    return result


def write_skill(root, name="example", *, metadata=None, body="# Valid knowledge", raw=None):
    directory = root / name
    directory.mkdir(parents=True, exist_ok=True)
    values = {"name": name, "description": "Example knowledge", "when_to_use": "When relevant",
              "agents": ["director"], "tools": ["list_models"], "related": [], "version": 1}
    values.update(metadata or {})
    content = raw if raw is not None else "---\n" + yaml.safe_dump(values, allow_unicode=True) + "---\n" + body
    (directory / "SKILL.md").write_text(content, encoding="utf-8")
    return directory


def library(root, **kwargs):
    return SkillLibrary(root, registry(), **kwargs)


def resource(directory, name="resources/example.md", content=b"cached text"):
    target = directory / name
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_bytes(content)
    return target


def test_repository_library_has_twenty_guides_and_no_premature_blueprints():
    result = library(Path(__file__).resolve().parents[1] / "skills", strict=True)
    assert len(result.names()) == 20
    assert {"image-edit", "image-create", "single-clip", "story-video", "video-remix", "video-transform"} <= set(result.names())
    assert all(not skill["blueprint"] for skill in result.list_skills())
    for name in ("intent-analysis", "delegation-policy", "long-form-video", "character-consistency"):
        assert "待 Claude 审定" in result.load_skill(name)["body"]
    assert "演示数据" in result.read_skill_resource("budget-planning", "resources/duration-and-cost.md")["content"]


def test_valid_skill_filters_and_returns_defensive_results(tmp_path):
    write_skill(tmp_path, metadata={"description": "多镜头 Video Planning"})
    write_skill(tmp_path, "shared", metadata={"agents": []})
    result = library(tmp_path, strict=True)
    assert [row["name"] for row in result.list_skills("director", "VIDEO")] == ["example"]
    assert [row["name"] for row in result.list_skills("research")] == ["shared"]
    assert result.list_skills(query="不存在") == []
    summary = result.list_skills()
    summary[0]["description"] = "mutated"
    loaded = result.load_skill("example")
    loaded["body"] = "mutated"
    loaded["resources"].append("outside.md")
    assert result.list_skills()[0]["description"] != "mutated"
    assert result.load_skill("example")["resources"] == []
    assert result.load_skill("example")["body"] != "mutated"


@pytest.mark.parametrize("metadata", [
    {"name": "different"}, {"name": "Uppercase"}, {"description": ""}, {"description": "x" * 201},
    {"when_to_use": "x" * 301}, {"version": 0}, {"version": True}, {"version": "1"},
    {"agents": ["unknown"]}, {"agents": ["director", "director"]}, {"agents": "director"},
    {"tools": ["missing_tool"]}, {"tools": ["list_models", "list_models"]}, {"tools": [" list_models"]},
    {"related": ["missing"]}, {"related": ["example", "example"]}, {"unknown": "field"},
    {"blueprint": {"builder": "os:path", "params_schema": {"type": "object"}}},
    {"blueprint": {"builder": "app.plans.blueprints.missing:build", "params_schema": {"type": "object"}}},
    {"blueprint": {"builder": "app.plans.blueprints.test:build", "params_schema": {"type": "array"}}},
])
def test_invalid_metadata_excluded_and_strict_mode_errors(tmp_path, metadata):
    write_skill(tmp_path, metadata=metadata)
    result = library(tmp_path)
    assert result.names() == []
    assert result.errors
    with pytest.raises(SkillLibraryError):
        library(tmp_path, strict=True)


@pytest.mark.parametrize("raw", [
    "name: example\nNo frontmatter", "---\nname: example\n", "---\n[]\n---\nbody",
    "---\nname: example\nname: example\n---\nbody",
    "---\n1: value\n---\nbody", "---\nitem: !!python/object/apply:os.system [echo]\n---\nbody",
    "---\na: &value []\nb: *value\n---\nbody",
    "---\na: {b: 1, b: 2}\n---\nbody",
    "---\nx: " + "[" * 40 + "1" + "]" * 40 + "\n---\nbody",
    "---\nx: [" + ",".join("1" for _ in range(2200)) + "]\n---\nbody",
    "---\n" + "# " + "x" * 17000 + "\n---\nbody",
], ids=["no_header", "unclosed", "list", "duplicate", "number_key", "object", "alias", "nested_duplicate", "deep", "many_nodes", "large"])
def test_unsafe_or_malformed_yaml_is_not_loaded(tmp_path, raw):
    write_skill(tmp_path, raw=raw)
    assert library(tmp_path).names() == []


def test_duplicate_name_cannot_shadow_valid_directory(tmp_path):
    write_skill(tmp_path)
    write_skill(tmp_path, "second", metadata={"name": "example"})
    result = library(tmp_path)
    assert result.names() == ["example"]
    assert len(result.errors) == 1


def test_related_failures_propagate_transitively(tmp_path, caplog):
    write_skill(tmp_path, "a", metadata={"related": ["b"]})
    write_skill(tmp_path, "b", metadata={"related": ["c"]})
    write_skill(tmp_path, "c", metadata={"tools": ["missing"]})
    write_skill(tmp_path, "valid")
    with caplog.at_level(logging.ERROR):
        result = library(tmp_path, logger=logging.getLogger("skill-test"))
    assert result.names() == ["valid"]
    assert len(result.errors) == 3
    assert caplog.text.count("Agent Skill validation failed") == 3


def test_related_cycles_are_knowledge_links_not_execution(tmp_path):
    write_skill(tmp_path, "a", metadata={"related": ["b"]})
    write_skill(tmp_path, "b", metadata={"related": ["a"]})
    assert library(tmp_path, strict=True).names() == ["a", "b"]


@pytest.mark.parametrize("body", ["", "x" * 12001], ids=["empty", "too_long"])
def test_body_limit(tmp_path, body):
    write_skill(tmp_path, body=body)
    with pytest.raises(SkillLibraryError):
        library(tmp_path, strict=True)


def test_body_limit_counts_characters_and_accepts_boundary(tmp_path):
    write_skill(tmp_path, body="图" * 12000)
    assert len(library(tmp_path, strict=True).load_skill("example")["body"]) == 12000


@pytest.mark.parametrize("name", ["Upper", "has space", "under_score", "-leading", "trailing-"])
def test_invalid_directory_names_rejected(tmp_path, name):
    write_skill(tmp_path, name)
    assert library(tmp_path).names() == []


def test_absent_root_and_missing_skill_file_are_errors(tmp_path):
    assert library(tmp_path / "missing").errors
    (tmp_path / "empty").mkdir()
    assert library(tmp_path).errors


def test_non_skill_root_files_are_ignored(tmp_path):
    (tmp_path / "README.md").write_text("Repository notes", encoding="utf-8")
    write_skill(tmp_path)
    assert library(tmp_path, strict=True).names() == ["example"]


@pytest.mark.parametrize("case", ["root", "directory", "manifest", "resource", "nested_directory"])
def test_symlink_components_are_rejected_without_platform_privileges(tmp_path, monkeypatch, case):
    directory = write_skill(tmp_path)
    target = resource(directory)
    selected = {"root": tmp_path, "directory": directory, "manifest": directory / "SKILL.md",
                "resource": target, "nested_directory": target.parent}[case]
    original = Path.is_symlink
    monkeypatch.setattr(Path, "is_symlink", lambda path: path == selected or original(path))
    assert library(tmp_path).names() == []


def test_resolved_resource_escape_is_rejected_even_without_symlink_flag(tmp_path, monkeypatch):
    directory = write_skill(tmp_path / "skills")
    target = resource(directory)
    outside = tmp_path / "outside.md"
    outside.write_text("secret", encoding="utf-8")
    original = Path.resolve
    monkeypatch.setattr(Path, "resolve", lambda path, *a, **kw: outside if path == target else original(path, *a, **kw))
    assert library(tmp_path / "skills").names() == []


@pytest.mark.parametrize("content", [b"x" * 65537, b"\xff\xfe", b"a\x00b", b"a\x01b"], ids=["too_large", "invalid_utf8", "nul", "control"])
def test_resource_size_and_utf8_text_bounds(tmp_path, content):
    resource(write_skill(tmp_path), content=content)
    assert library(tmp_path).names() == []


def test_resource_max_bytes_and_unicode_supported(tmp_path):
    directory = write_skill(tmp_path)
    resource(directory, content=b"x" * 65536)
    resource(directory, "resources/中文.txt", "测试\n".encode("utf-8"))
    result = library(tmp_path, strict=True)
    assert len(result.read_skill_resource("example", "resources/example.md")["content"]) == 65536
    assert result.read_skill_resource("example", "resources/中文.txt")["content"] == "测试\n"


@pytest.mark.parametrize("path", [
    "../outside.md", "resources/../../outside.md", "/outside.md", "C:/outside.md", "C:outside.md",
    "\\\\server\\share\\secret", "resources\\example.md", "resources//example.md", "./resources/example.md",
    "resources/./example.md", "resources/../example.md", "resources/a:stream", ".hidden", "resources/name.",
    "resources/name ", "resources/evil\x00.md", "", "resources/",
])
def test_resource_traversal_and_windows_paths_fail_closed(tmp_path, path):
    resource(write_skill(tmp_path))
    result = library(tmp_path, strict=True)
    with pytest.raises(AppError) as error:
        result.read_skill_resource("example", path)
    assert error.value.code == "INVALID_SKILL_RESOURCE"


def test_resources_are_startup_snapshot_no_live_file_read(tmp_path):
    directory = write_skill(tmp_path)
    target = resource(directory)
    result = library(tmp_path, strict=True)
    target.write_text("unreviewed mutation", encoding="utf-8")
    (directory / "SKILL.md").write_text("unreviewed mutation", encoding="utf-8")
    resource(directory, "new.md", b"new")
    assert result.read_skill_resource("example", "resources/example.md")["content"] == "cached text"
    assert result.load_skill("example")["body"] == "# Valid knowledge"
    assert result.load_skill("example")["resources"] == ["resources/example.md"]
    with pytest.raises(AppError) as error:
        result.read_skill_resource("example", "new.md")
    assert error.value.code == "SKILL_RESOURCE_NOT_FOUND"


def test_unknown_skill_and_unlisted_manifest_are_not_read(tmp_path):
    write_skill(tmp_path)
    result = library(tmp_path)
    with pytest.raises(AppError) as error:
        result.load_skill("missing")
    assert error.value.code == "SKILL_NOT_FOUND"
    with pytest.raises(AppError) as error:
        result.read_skill_resource("example", "SKILL.md")
    assert error.value.code == "SKILL_RESOURCE_NOT_FOUND"


@pytest.mark.parametrize("callable_builder", [True, False])
def test_blueprint_builder_must_resolve_callable_but_is_not_executed(tmp_path, monkeypatch, callable_builder):
    module = ModuleType("app.plans.blueprints.test")
    calls = []
    module.build = (lambda: calls.append("executed")) if callable_builder else 42
    monkeypatch.setitem(sys.modules, module.__name__, module)
    write_skill(tmp_path, metadata={"blueprint": {"builder": "app.plans.blueprints.test:build",
                                               "params_schema": {"type": "object", "properties": {}}}})
    result = library(tmp_path)
    assert bool(result.names()) == callable_builder
    if callable_builder:
        assert result.list_skills()[0]["blueprint"] is True
    assert calls == []


def test_initialize_and_registry_tools_are_read_only_and_cached(app_ctx, tmp_path):
    resource(write_skill(tmp_path / "library"), content=b"  cached text\n")
    catalog = registry()
    cached = initialize_skill_library(app_ctx, catalog, root=tmp_path / "library", strict=True)
    assert get_skill_library() is cached
    row = AgentRun(owner_id="owner", request_key=new_id("request"), request={
        "schema_version": 3, "text": "规划一段视频", "budget_limit": 20,
    }, snapshot={})
    db.session.add(row)
    db.session.commit()

    def invoke(name, args):
        ctx = ToolContext(role="director", caller_agent="director", delegation_id=1,
                          agent_step=0, budget_scope=row.run_id, budget_limit=20)
        return catalog.invoke(name, args, ctx)

    listed = invoke("list_skills", {"agent": "director"})
    assert listed["output"][0]["name"] == "example"
    loaded = invoke("load_skill", {"name": "example"})
    assert loaded["output"]["resources"] == ["resources/example.md"]
    read = invoke("read_skill_resource", {"name": "example", "path": "resources/example.md"})
    assert read["output"]["content"] == "  cached text\n"
    assert all(item["estimated_cost"] == 0 and item["invocation_id"] is None for item in (listed, loaded, read))
    assert ToolInvocation.query.count() == 0
    assert "agent_v3_scripted_llm" not in app_ctx.extensions
    assert not {"list_skills", "load_skill", "read_skill_resource"} & set(build_default_registry().names())
    schemas = catalog.function_schemas(["list_skills", "load_skill", "read_skill_resource"])
    assert len(schemas) == 3
    assert all(schema["function"]["parameters"]["additionalProperties"] is False for schema in schemas)


@pytest.mark.parametrize("name,args", [
    ("list_skills", {"agent": "unknown"}), ("list_skills", {"query": "x" * 201}),
    ("load_skill", {"name": "../outside"}), ("load_skill", {"name": "example", "extra": True}),
    ("read_skill_resource", {"name": "example", "path": ""}),
])
def test_tool_input_schema_rejects_malformed_values(app_ctx, name, args):
    with pytest.raises(AppError) as error:
        registry().invoke(name, args, ToolContext(role="system"))
    assert error.value.code == "INVALID_INPUT"


def test_uninitialized_library_is_explicit_failure(app_ctx):
    app_ctx.extensions.pop(EXTENSION_KEY, None)
    with pytest.raises(AppError) as error:
        registry().invoke("list_skills", {}, ToolContext(role="system"))
    assert error.value.code == "SKILL_LIBRARY_UNAVAILABLE"


def test_skill_tools_do_not_expand_role_permissions(app_ctx):
    with pytest.raises(AppError) as error:
        registry().invoke("list_skills", {}, ToolContext(role="production"))
    assert error.value.code == "TOOL_FORBIDDEN"
