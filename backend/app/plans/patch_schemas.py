"""Author-controlled Patch decisions contain no execution or review authority."""

from typing import Annotated, Literal

from pydantic import Field, model_validator

from app.agent.request_spec import StrictModel
from app.agents.schemas import NodeId, PlanDraftNode, WorkspaceRef


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


class PatchDraft(StrictModel):
    base_version: int = Field(ge=1, strict=True)
    reason: str = Field(min_length=1, max_length=2000)
    evidence_refs: list[TaskEvidence | ArtifactEvidence | WorkspaceEvidence] = Field(default_factory=list, max_length=40)
    ops: list[PatchOperation] = Field(min_length=1, max_length=50)
    scope: Literal["only", "cascade"] = "only"

    @model_validator(mode="after")
    def unique_targets(self):
        targets = [item.node.id if isinstance(item, InsertNode) else item.node_id for item in self.ops]
        if len(targets) != len(set(targets)):
            raise ValueError("A Patch may target each node only once")
        return self
