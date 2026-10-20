"""Immutable Director evidence for intent-preserving Patch approval."""
from typing import Literal

from pydantic import Field, ValidationError, field_validator, model_validator

from app.agent.plan_versions import inputs_hash
from app.agent.request_spec import StrictModel
from app.agents.schemas import validate_payload
from app.api import AppError
from app.extensions import db
from app.models import AgentDelegation, AgentWorkspaceItem


class ChangedElement(StrictModel):
    element: str = Field(min_length=1, max_length=300)
    change: Literal["changed", "removed"]
    before: str = Field(min_length=1, max_length=1000)
    after: str = Field(max_length=1000)
    reason: str = Field(min_length=1, max_length=1000)

    @field_validator("element", "before", "reason")
    @classmethod
    def nonblank(cls, value):
        if not value.strip():
            raise ValueError("Intent change descriptions must not be blank")
        return value


    @model_validator(mode="after")
    def changed_after_is_nonblank(self):
        if self.change == "changed" and not self.after.strip():
            raise ValueError("A changed element requires its new content")
        return self


class IntentAssessment(StrictModel):
    intent_preserved: bool = Field(strict=True)
    changed_elements: list[ChangedElement] = Field(max_length=40)


def assessment_key(request_key):
    # A distinct bounded key avoids the workspace's unique Run/request key.
    return "patch-assessment:" + inputs_hash({"request_key": request_key})


def _payload(patch_id, review, draft_hash):
    assessment = IntentAssessment.model_validate({key: review[key]
        for key in ("intent_preserved", "changed_elements")}).model_dump(mode="json")
    return validate_payload("note", {"schema_version": 1, "patch_id": patch_id,
        "base_version": review["base_version"], "draft_hash": draft_hash,
        "verdict": review["verdict"], "reason": review["reason"],
        "request_key": review["request_key"], **assessment})


def save_assessment(run, delegation, patch_id, review):
    payload = _payload(patch_id, review, review["draft_hash"])
    key = f"patch.{patch_id}.intent"
    row = AgentWorkspaceItem(run_id=run.run_id, key=key, version=1,
        kind="note", payload=payload, artifact_ids=[], author_agent=delegation.agent,
        delegation_id=delegation.id, request_key=assessment_key(review["request_key"]),
        inputs_hash=inputs_hash({"key": key, "kind": "note", "payload": payload}))
    db.session.add(row)
    return {"key": key, "version": 1}


def verified_assessment(run, record, draft_hash):
    """Legacy reviews remain unknown; partial or forged new evidence is rejected."""
    review = record.get("director_review") or {}
    markers = {"intent_preserved", "changed_elements", "assessment_ref"}
    if not markers.intersection(review):
        return None
    try:
        if not markers.issubset(review):
            raise ValueError("Incomplete intent assessment")
        ref = review["assessment_ref"]
        if (not isinstance(ref, dict) or set(ref) != {"key", "version"}
                or ref["key"] != f"patch.{record['patch_id']}.intent"
                or type(ref["version"]) is not int or ref["version"] != 1
                or type(review.get("delegation_id")) is not int
                or not isinstance(review.get("request_key"), str) or not review["request_key"]):
            raise ValueError("Invalid intent evidence reference")
        expected = _payload(record["patch_id"], review, draft_hash)
        director = db.session.get(AgentDelegation, review["delegation_id"])
        row = AgentWorkspaceItem.query.filter_by(run_id=run.run_id,
            key=ref["key"], version=ref["version"]).first()
        if (director is None or director.agent != "director" or director.run_id != run.run_id
                or record.get("review_delegation_id") != director.id
                or record.get("author_delegation_id") == director.id
                or row is None or row.kind != "note" or row.author_agent != "director"
                or row.delegation_id != director.id
                or row.request_key != assessment_key(review["request_key"])
                or row.payload != expected or row.inputs_hash != inputs_hash({
                    "key": row.key, "kind": "note", "payload": expected})):
            raise ValueError("Intent evidence does not match the assigned review")
        return {key: expected[key] for key in ("intent_preserved", "changed_elements")}
    except (KeyError, TypeError, ValueError, ValidationError) as error:
        raise AppError("PATCH_REVIEW_REQUIRED", "Patch intent assessment lacks matching immutable Director evidence", 403) from error


def automatic_intent_reasons(assessment):
    if not assessment:
        return ["PATCH_INTENT_UNCERTAIN"]
    if assessment.get("changed_elements"):
        return ["PATCH_INTENT_CHANGED"]
    if assessment.get("intent_preserved") is not True:
        return ["PATCH_INTENT_UNCERTAIN"]
    return []


def public_assessment(run, record):
    from app.plans.patches import patch_digest
    try:
        assessment = verified_assessment(run, record, patch_digest(record.get("draft")))
    except (AppError, KeyError, TypeError, ValueError):
        assessment = None
    return assessment or {"intent_preserved": None, "changed_elements": []}
