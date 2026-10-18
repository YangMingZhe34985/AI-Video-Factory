"""Validated, immutable startup snapshot of repository-authored Agent knowledge."""

from dataclasses import dataclass
from importlib import import_module
import json
from pathlib import Path, PurePosixPath, PureWindowsPath
import re
from types import MappingProxyType

from flask import current_app
from pydantic import BaseModel, ConfigDict, Field, ValidationError, field_validator
import yaml

from app.api import AppError


AGENT_NAMES = frozenset({"producer", "research", "creative", "director", "prompt_smith", "critic", "repair"})
NAME_PATTERN = r"^[a-z][a-z0-9]*(?:-[a-z0-9]+)*$"
MAX_RESOURCE_BYTES = 64 * 1024
MAX_BODY_CHARS = 12_000
MAX_FRONTMATTER_BYTES = 16 * 1024
EXTENSION_KEY = "agent_v3_skill_library"


class SkillLibraryError(ValueError):
    def __init__(self, errors):
        self.errors = tuple(errors)
        super().__init__("Invalid Skill library: " + "; ".join(self.errors))


class _StrictSafeLoader(yaml.SafeLoader):
    """No duplicate keys, merge keys, aliases, or Python constructors."""

    def compose_node(self, parent, index):
        if self.check_event(yaml.AliasEvent):
            raise ValueError("YAML aliases are not allowed")
        self._node_count = getattr(self, "_node_count", 0) + 1
        self._node_depth = getattr(self, "_node_depth", 0) + 1
        if self._node_count > 2048 or self._node_depth > 32:
            raise ValueError("YAML structure exceeds limits")
        try:
            return super().compose_node(parent, index)
        finally:
            self._node_depth -= 1

    def construct_mapping(self, node, deep=False):
        if not isinstance(node, yaml.MappingNode):
            raise ValueError("Expected a YAML mapping")
        result = {}
        for key_node, value_node in node.value:
            key = self.construct_object(key_node, deep=deep)
            if not isinstance(key, str) or key in result:
                raise ValueError("YAML keys must be unique strings")
            result[key] = self.construct_object(value_node, deep=deep)
        return result


class _MetadataModel(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True, str_strip_whitespace=True, allow_inf_nan=False)


class BlueprintMetadata(_MetadataModel):
    builder: str = Field(pattern=r"^app\.plans\.blueprints\.[a-z][a-z0-9_]*:[a-z][a-z0-9_]*$")
    params_schema: dict

    @field_validator("params_schema")
    @classmethod
    def object_schema(cls, value):
        if value.get("type") != "object" or not isinstance(value.get("properties", {}), dict):
            raise ValueError("Blueprint params_schema must be an object JSON Schema")
        json.dumps(value, allow_nan=False)
        return value


class SkillMetadata(_MetadataModel):
    name: str = Field(min_length=1, max_length=80, pattern=NAME_PATTERN)
    description: str = Field(min_length=1, max_length=200)
    when_to_use: str = Field(min_length=1, max_length=300)
    agents: list[str] = Field(default_factory=list, max_length=7)
    tools: list[str] = Field(default_factory=list, max_length=80)
    related: list[str] = Field(default_factory=list, max_length=80)
    version: int = Field(ge=1)
    blueprint: BlueprintMetadata | None = None

    @field_validator("agents", "tools", "related", mode="before")
    @classmethod
    def unique_names(cls, value, info):
        if not isinstance(value, list) or any(not isinstance(item, str) for item in value):
            return value
        if len(set(value)) != len(value) or any(not item or item.strip() != item for item in value):
            raise ValueError(f"{info.field_name} must contain unique nonempty names")
        if info.field_name == "agents" and not set(value) <= AGENT_NAMES:
            raise ValueError("Unknown recommended Agent")
        return value


@dataclass(frozen=True)
class _Skill:
    metadata: SkillMetadata
    body: str
    resources: object


def _safe_relative_path(value):
    if not isinstance(value, str) or not value or len(value) > 512:
        raise ValueError("Invalid resource path")
    if "\\" in value or ":" in value or "\x00" in value or PureWindowsPath(value).drive:
        raise ValueError("Resource paths must be relative POSIX paths")
    parts = value.split("/")
    if any(part in {"", ".", ".."} or part.endswith((".", " ")) for part in parts):
        raise ValueError("Resource path traversal is not allowed")
    path = PurePosixPath(value)
    if path.is_absolute() or any(part.startswith(".") for part in parts):
        raise ValueError("Hidden or absolute resource paths are not allowed")
    return path


def _bounded_text(path, root, *, limit=MAX_RESOURCE_BYTES):
    relative = path.relative_to(root)
    current = root
    for part in relative.parts:
        current = current / part
        if current.is_symlink():
            raise ValueError("Skill symlinks are not allowed")
    resolved = path.resolve(strict=True)
    if not resolved.is_relative_to(root.resolve(strict=True)) or not resolved.is_file():
        raise ValueError("Skill file is outside its directory")
    with resolved.open("rb") as stream:
        content = stream.read(limit + 1)
    if len(content) > limit:
        raise ValueError(f"Text file exceeds {limit} bytes")
    text = content.decode("utf-8-sig")
    if any(ord(char) < 32 and char not in "\n\r\t" for char in text):
        raise ValueError("Skill resources must be UTF-8 text")
    return text


def _load_directory(directory, root, registry):
    if directory.is_symlink() or not re.fullmatch(NAME_PATTERN, directory.name):
        raise ValueError("Invalid Skill directory")
    text = _bounded_text(directory / "SKILL.md", root)
    lines = text.splitlines(keepends=True)
    if not lines or lines[0].strip() != "---":
        raise ValueError("SKILL.md requires YAML frontmatter")
    end = next((index for index in range(1, len(lines)) if lines[index].strip() == "---"), None)
    if end is None:
        raise ValueError("Unclosed YAML frontmatter")
    frontmatter = "".join(lines[1:end])
    if len(frontmatter.encode("utf-8")) > MAX_FRONTMATTER_BYTES:
        raise ValueError("Skill frontmatter is too large")
    metadata = SkillMetadata.model_validate(yaml.load(frontmatter, Loader=_StrictSafeLoader))
    if metadata.name != directory.name:
        raise ValueError("Skill name must equal its directory name")
    if not set(metadata.tools) <= set(registry.names()):
        raise ValueError("Skill references an unavailable tool")
    if metadata.blueprint:
        module_name, function_name = metadata.blueprint.builder.split(":")
        if not callable(getattr(import_module(module_name), function_name, None)):
            raise ValueError("Blueprint builder is not callable")
    body = "".join(lines[end + 1:]).strip()
    if not body or len(body) > MAX_BODY_CHARS:
        raise ValueError("Skill body must contain 1..12000 characters")
    resources = {}
    for file in sorted(directory.rglob("*")):
        if file.is_symlink():
            raise ValueError("Skill symlinks are not allowed")
        if file.is_dir() or file.name == "SKILL.md" and file.parent == directory:
            continue
        relative = file.relative_to(directory).as_posix()
        _safe_relative_path(relative)
        resources[relative] = _bounded_text(file, directory)
    return _Skill(metadata, body, MappingProxyType(resources))


class SkillLibrary:
    def __init__(self, root, registry, *, strict=False, logger=None):
        self.root = Path(root)
        entries, errors = {}, []
        if self.root.is_symlink() or not self.root.is_dir():
            errors.append("Skill root must be an existing regular directory")
        else:
            for directory in sorted(self.root.iterdir()):
                if not directory.is_dir() and not directory.is_symlink():
                    continue
                try:
                    skill = _load_directory(directory, self.root, registry)
                    if skill.metadata.name in entries:
                        raise ValueError("Duplicate Skill name")
                    entries[skill.metadata.name] = skill
                except (OSError, UnicodeError, ValueError, TypeError, ImportError, yaml.YAMLError, ValidationError) as error:
                    errors.append(f"{directory.name}: {error}")
            # Removing invalid dependencies must propagate, independent of scan order.
            while True:
                invalid = [name for name, skill in entries.items() if not set(skill.metadata.related) <= set(entries)]
                if not invalid:
                    break
                for name in invalid:
                    errors.append(f"{name}: Skill references an unavailable related Skill")
                    del entries[name]
        self._entries = MappingProxyType(entries)
        self.errors = tuple(errors)
        for error in errors:
            if logger:
                logger.error("Agent Skill validation failed: %s", error)
        if errors and strict:
            raise SkillLibraryError(errors)

    def names(self):
        return sorted(self._entries)

    def list_skills(self, agent=None, query=None):
        search = query.casefold() if query else None
        result = []
        for name in self.names():
            metadata = self._entries[name].metadata
            if agent and metadata.agents and agent not in metadata.agents:
                continue
            if search and search not in " ".join((name, metadata.description, metadata.when_to_use)).casefold():
                continue
            result.append({"name": name, "description": metadata.description,
                           "when_to_use": metadata.when_to_use, "blueprint": metadata.blueprint is not None})
        return result

    def _get(self, name):
        if name not in self._entries:
            raise AppError("SKILL_NOT_FOUND", "Unknown or invalid Skill", 404)
        return self._entries[name]

    def load_skill(self, name):
        skill = self._get(name)
        return {"name": name, "version": skill.metadata.version, "body": skill.body,
                "resources": sorted(skill.resources)}

    def read_skill_resource(self, name, path):
        skill = self._get(name)
        try:
            _safe_relative_path(path)
        except ValueError as error:
            raise AppError("INVALID_SKILL_RESOURCE", str(error), 422) from error
        if path not in skill.resources:
            raise AppError("SKILL_RESOURCE_NOT_FOUND", "Unknown Skill text resource", 404)
        return {"name": name, "path": path, "content": skill.resources[path]}


def initialize_skill_library(app, registry, *, root=None, strict=False):
    """Call after the private v3 catalog is registered; never mutate old tools."""
    directory = root if root is not None else Path(app.root_path).parent / "skills"
    library = SkillLibrary(directory, registry, strict=strict, logger=app.logger)
    app.extensions[EXTENSION_KEY] = library
    return library


def get_skill_library():
    library = current_app.extensions.get(EXTENSION_KEY)
    if library is None:
        raise AppError("SKILL_LIBRARY_UNAVAILABLE", "The Skill library has not been initialized", 503)
    return library
