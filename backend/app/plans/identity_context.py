"""Bind identity requirements to an immutable Run-local story, without writes."""
from copy import deepcopy

from pydantic import ValidationError

from app.agent.story_spec import StoryPackage
from app.models import AgentPlanVersion, AgentWorkspaceItem


def bind_story(plan, run, raw):
    issues = []

    def issue(code, message):
        issues.append({"code": code, "node_id": None, "message": message})

    # Only an exact persisted legacy envelope gets compatibility treatment.
    # Author-supplied server fields cannot manufacture this exemption.
    if (isinstance(raw, dict) and type(raw.get("plan_version")) is int
            and not raw.get("story_ref") and not raw.get("character_references")
            and not any("characters" in node for node in raw.get("nodes", []))):
        stored = AgentPlanVersion.query.filter_by(run_id=run.run_id, version=raw["plan_version"]).first()
        if stored is not None and stored.plan == raw:
            return issues

    ref = plan.get("story_ref")
    query = AgentWorkspaceItem.query.filter_by(run_id=run.run_id, kind="story")
    row = query.filter_by(key=ref["key"], version=ref["version"]).first() if ref else query.order_by(
        AgentWorkspaceItem.id.desc()).first()
    if row is None:
        if ref:
            issue("PLAN_INVALID_STORY_REFERENCE", "Story reference must name a story in this Run")
        return issues
    try:
        story = StoryPackage.model_validate(row.payload)
    except ValidationError:
        issue("PLAN_INVALID_STORY_REFERENCE", "Referenced story does not match the story contract")
        return issues
    plan["story_ref"] = {"key": row.key, "version": row.version}
    catalog = plan.get("character_references", {})
    expected = {character.character_id for character in story.characters}
    for cid in sorted(expected - set(catalog)):
        issue("PLAN_CHARACTER_REFERENCE_REQUIRED",
              f"Character {cid} needs a character_references entry; preserve its references or add a preview identity image")
    for cid in sorted(set(catalog) - expected):
        issue("PLAN_UNKNOWN_CHARACTER", f"Character {cid} is absent from the bound story")
    for character in story.characters:
        refs = catalog.get(character.character_id)
        if refs is None:
            continue
        originals = [{"artifact": key} for key in character.reference.artifact_ids]
        if originals:
            if sorted(refs, key=str) != sorted(originals, key=str):
                issue("PLAN_INVALID_CHARACTER_REFERENCE",
                      f"Character {character.character_id} must preserve every bound story reference image")
        elif (len(refs) != 1 or set(refs[0]) != {"ref"}):
            issue("PLAN_INVALID_CHARACTER_REFERENCE",
                  f"Character {character.character_id} needs one single-image preview identity node")
    return deepcopy(issues)
