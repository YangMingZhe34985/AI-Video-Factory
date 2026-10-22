"""Author-controlled Patch decisions contain no execution or review authority."""

import json
from typing import Annotated, Literal

from pydantic import Field, model_serializer, model_validator

from app.agent.request_spec import StrictModel
from app.agents.schemas import CharacterId, IdentityReferences, NodeId, PlanDraftNode, WorkspaceRef


class TaskEvidence(StrictModel):
    task_id: int = Field(ge=1, strict=True)


class ArtifactEvidence(StrictModel):
    artifact_id: str = Field(min_length=1, max_length=100)


class WorkspaceEvidence(StrictModel):
    workspace_ref: WorkspaceRef


class UpdateInputs(StrictModel):
    op: Literal["update_inputs"]
    node_id: NodeId
    inputs: dict


class ReplaceNode(StrictModel):
    op: Literal["replace_node"]
    node_id: NodeId
    node: PlanDraftNode

    @model_validator(mode="after")
    def same_id(self):
        if self.node.id != self.node_id:
            raise ValueError("Replacement must preserve its node ID")
        return self


class InsertNode(StrictModel):
    op: Literal["insert_node"]
    node: PlanDraftNode
    before: NodeId | None = None


class RemoveNode(StrictModel):
    op: Literal["remove_node"]
    node_id: NodeId


PatchOperation = Annotated[UpdateInputs | ReplaceNode | InsertNode | RemoveNode, Field(discriminator="op")]


class IdentityUpgrade(StrictModel):
    """One-time binding for a previously identity-free approved Plan."""

    character_references: dict[CharacterId, IdentityReferences] = Field(min_length=1, max_length=8)
    story_ref: WorkspaceRef | None = None

    @model_validator(mode="after")
    def valid_references(self):
        for refs in self.character_references.values():
            if not 1 <= len(refs) <= 3:
                raise ValueError("Each character needs one to three identity references")
            tokens = [json.dumps(ref.model_dump(), sort_keys=True) for ref in refs]
            if len(set(tokens)) != len(tokens):
                raise ValueError("Character references must be unique")
        return self


class PatchDraft(StrictModel):
    base_version: int = Field(ge=1, strict=True)
    reason: str = Field(min_length=1, max_length=2000)
    evidence_refs: list[TaskEvidence | ArtifactEvidence | WorkspaceEvidence] = Field(default_factory=list, max_length=40)
    ops: list[PatchOperation] = Field(min_length=1, max_length=200)
    scope: Literal["only", "cascade"] = "only"
    identity_upgrade: IdentityUpgrade | None = None

    @model_validator(mode="before")
    @classmethod
    def reject_model_projection(cls, value):
        from app.plans.projection_input import reject_context_projection
        return reject_context_projection(value)

    @model_validator(mode="after")
    def unique_targets(self):
        if self.identity_upgrade is None and len(self.ops) > 50:
            raise ValueError("Ordinary patches allow at most 50 operations")
        targets = [item.node.id if isinstance(item, InsertNode) else item.node_id for item in self.ops]
        if len(targets) != len(set(targets)):
            raise ValueError("A Patch may target each node only once")
        return self

    @model_serializer(mode="wrap")
    def compatible_shape(self, handler):
        value = handler(self)
        if self.identity_upgrade is None:
            value.pop("identity_upgrade", None)
        return value
