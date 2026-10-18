"""Offline scenario support: only model answers are scripted, never tool effects."""
from copy import deepcopy
from io import BytesIO
import json
import subprocess

from PIL import Image

from app.agents import runtime
from app.agents.budget import planning_spent
from app.agents.cards import get_catalog
from app.extensions import db
from app.models import AgentDelegation, AgentPlanVersion, AgentRun, AgentWorkspaceItem, ApiTask, PlanNodeTask, ToolInvocation
from app.services.video_compression_service import VideoCompressionService
from app.tools.scripted_llm import ScriptedLLM

ROLES = ("producer", "research", "creative", "director", "prompt_smith", "critic", "repair")
PAID_GENERATION = {"generate_image", "animate_shot", "generate_video", "transform_video", "request_preview"}


def call(name, arguments, identity=None):
    return {"id": identity or name, "name": name, "arguments": arguments}


def write(key, kind, payload):
    return call("write_workspace", {"key": key, "kind": kind, "payload": payload}, "write_" + key)


def read(ref):
    return call("read_workspace", ref, "read_" + ref["key"])


def finish(**fields):
    return call("finish", {"kind": "completed", **fields})


def delegate(agent, refs, *, task, expected, **extra):
    return call("delegate", {"agent": agent, "task": task, "context_refs": refs, "expected": expected, **extra}, "delegate_" + agent)


def upload_image(client, color="#5c83a3"):
    stream = BytesIO()
    Image.new("RGB", (320, 320), color).save(stream, "PNG")
    stream.seek(0)
    response = client.post("/api/agent/attachments", data={"file": (stream, "reference.png")})
    assert response.status_code == 201, response.json
    return response.json["data"]["attachment_id"]


def upload_video(client, tmp_path):
    path = tmp_path / "source.mp4"
    subprocess.run([VideoCompressionService.resolve_ffmpeg(), "-y", "-v", "error", "-f", "lavfi", "-i",
                    "color=c=blue:s=320x320:r=12:d=3", "-an", "-c:v", "libx264", "-pix_fmt", "yuv420p", str(path)],
                   check=True, capture_output=True, timeout=30)
    with path.open("rb") as stream:
        response = client.post("/api/agent/attachments", data={"file": (stream, "source.mp4")})
    assert response.status_code == 201, response.json
    return response.json["data"]["attachment_id"]


def attachment(artifact_id, role, *, kind="image", reason="Use this owned source for the requested creation"):
    return {"attachment_id": artifact_id, "kind": kind, "role": role,
            "description": "Offline scenario fixture", "reason": reason}


def brief(deliverable, summary, *, attachments=(), **extra):
    return {"deliverable": deliverable, "summary": summary, "attachments": list(attachments),
            "confidence": 0.9, **extra}


def image_plan(*, refs=(), mode="t2i", prompt="A cat in a blue suit"):
    return {"recipe": "image_edit" if mode == "i2i" else "image_create", "title": "Mock cat portrait",
            "rationale": "One image needs no specialist delegation", "image": {"mode": mode,
            "model_id": "wan2.7-image" if mode == "i2i" else "wan2.6-image", "prompt": prompt,
            "reference_attachment_ids": list(refs), "params": {}, "n": 1}}


def clip_plan(model, duration):
    result = image_plan()
    result.update(recipe="single_clip", video={"mode": "i2v", "model_id": model, "prompt": "The cat dances slowly",
        "first_frame": "generated_image", "params": {"duration": duration}})
    return result


class Scenario:
    """Advance the real runtime one scripted round at a time.

    Later answer arguments may include IDs observed from completed real tool
    receipts. No workspace row, invocation, Plan, approval or provider result
    is fabricated by the harness. Every Agent has an explicit script, so an
    unexpected delegation/step fails instead of falling back to a demo answer.
    """

    def __init__(self, app, client, text, *, attachment_ids=(), budget=100):
        self.app, self.client = app, client
        response = client.post("/api/agent/runs", json={"text": text, "request_key": "scenario",
            "attachment_ids": list(attachment_ids), "budget_limit": budget})
        assert response.status_code == 202, response.json
        self.run = AgentRun.query.filter_by(run_id=response.json["data"]["run_id"]).one()
        self.root = runtime.initialize(self.run)
        self.responses, self.calls = {role: [] for role in ROLES}, []
        assert self.root.credits_limit == 20

    def agent(self, role):
        return AgentDelegation.query.filter_by(run_id=self.run.run_id, agent=role).order_by(AgentDelegation.id.desc()).one()

    def step(self, role, calls, *, vision_ids=None):
        owner = self.agent(role)
        before = owner.steps
        self.responses[(role, before)] = calls
        if vision_ids is not None:
            self.responses[("vision", before)] = {"content": json.dumps({"images": [{"artifact_id": identity,
                "analysis": {"summary": "[Mock] visible reference", "subjects": [{"label": "character", "appearance": "green geometric costume"}],
                    "style": "[Mock] anime reference", "text_in_image": "", "has_human_face": False, "suggested_role": "identity_ref"}}
                for identity in vision_ids]})}
        scripted = ScriptedLLM(self.responses)
        scripted.calls = self.calls
        self.app.extensions["agent_v3_scripted_llm"] = scripted
        for _ in range(4):
            runtime.advance(self.run)
            db.session.refresh(owner)
            failure = (self.run.error, owner.error, {"agent": role, "steps": owner.steps,
                       "status": owner.status, "credits_limit": owner.credits_limit})
            assert self.run.status not in {"attention", "cancelled", "failed"}, failure
            assert owner.status not in {"failed", "limit", "cancelled", "returned"}, failure
            if owner.steps > before:
                return
        raise AssertionError((role, before, owner.status, self.run.status))

    def output(self, role, name):
        for item in reversed((self.agent(role).state or {}).get("messages", [])):
            if item.get("role") == "tool" and item.get("name") == name:
                result = json.loads(item["content"])
                assert not result.get("error"), result
                return result
        raise AssertionError((role, name))

    def workspace(self, ref):
        return deepcopy(AgentWorkspaceItem.query.filter_by(run_id=self.run.run_id, **ref).one().payload)

    def blueprint(self, role, name, params):
        self.step(role, [call("load_skill", {"name": name}), call("instantiate_blueprint", {"name": name, "params": params})])
        output = self.output(role, "instantiate_blueprint")
        assert output["issues"] == [], output["issues"]
        assert output["experimental"] is False
        return output["workspace_ref"]

    def submit(self, ref):
        self.step("producer", [read(ref), call("check_plan", {"plan": self.workspace(ref)}), call("submit_plan", {"plan_ref": ref})])
        assert self.output("producer", "check_plan")["issues"] == []
        assert self.output("producer", "submit_plan")["submitted"] is True
        assert self.run.status == "awaiting_plan_review"
        version = AgentPlanVersion.query.filter_by(run_id=self.run.run_id).one()
        assert version.check["dry_run"]["passed"] is True
        assert version.check["issues"] == []
        return version

    def assert_review_only(self, *, allow_analysis=False):
        assert not (self.run.snapshot or {}).get("v3_execution")
        assert PlanNodeTask.query.filter_by(run_id=self.run.run_id).count() == 0
        assert ToolInvocation.query.filter(ToolInvocation.budget_scope == self.run.run_id,
            ToolInvocation.tool_name.in_(PAID_GENERATION)).count() == 0
        assert all(task.node_run.node_key == "reverse_prompts" for task in ApiTask.query.all()) if allow_analysis else ApiTask.query.count() == 0
        assert planning_spent(self.run.run_id) <= self.root.credits_limit == 20
        for row in AgentDelegation.query.filter_by(run_id=self.run.run_id):
            card = get_catalog().cards[row.agent]
            assert row.steps <= card.limits.max_steps and row.llm_calls <= card.limits.max_llm_calls
        before = (list(self.calls), AgentPlanVersion.query.count(), ToolInvocation.query.count(), planning_spent(self.run.run_id))
        runtime.advance(self.run)
        runtime.advance(self.run)
        assert before == (self.calls, AgentPlanVersion.query.count(), ToolInvocation.query.count(), planning_spent(self.run.run_id))
        assert self.run.status == "awaiting_plan_review"
