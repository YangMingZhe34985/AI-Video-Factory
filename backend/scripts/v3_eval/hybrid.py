"""V10b real-Agent/Mock-media evidence driver; imports evaluation guards first.

Run only with EVAL_MOCK_MEDIA=1 and the same explicit EVAL_WORK_DIR as V10a.
Examples: python hybrid.py delivery --run-id RUN; story --run-id OTHER_RUN; failure-auto / failure-manual;
          choice --run-id RUN; crash (creates one new simple planning Run).
This module never manufactures an LLM response, Patch review or approval receipt.
"""
from __future__ import annotations

import argparse
from copy import deepcopy
import hashlib
import json
import os
from pathlib import Path
import subprocess
import sys
import time
import uuid

GENERATION_TOOLS = {"generate_image", "animate_shot", "generate_video", "transform_video"}
VIDEO_TOOLS = {"animate_shot", "generate_video", "transform_video"}


class ScenarioFailure(RuntimeError):
    pass


def require(condition, message):
    if not condition:
        raise ScenarioFailure(message)


def save_json(path, value):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(path.name + ".tmp")
    with temporary.open("w", encoding="utf-8") as stream:
        json.dump(value, stream, ensure_ascii=False, indent=2, default=str)
        stream.flush()
        os.fsync(stream.fileno())
    temporary.replace(path)


def digest(value):
    return hashlib.sha256(json.dumps(value, ensure_ascii=False, sort_keys=True, default=str).encode()).hexdigest()


def ordered_video_nodes(plan):
    """Read shot order from the delivered composition, never DAG declaration order."""
    nodes = {node["id"]: node for node in plan.get("nodes", [])}
    def refs(value):
        if isinstance(value, dict):
            if isinstance(value.get("ref"), str):
                yield value["ref"].split(".", 1)[0]
            else:
                for child in value.values():
                    yield from refs(child)
        elif isinstance(value, list):
            for child in value:
                yield from refs(child)
    def sources(node_id, ancestors=()):
        require(node_id not in ancestors, "Cyclic media dependency in reviewed plan")
        node = nodes[node_id]
        if node["tool"] in VIDEO_TOOLS:
            return [node_id]
        inputs = node.get("inputs", {})
        values = inputs.get("video_artifact_ids", []) if node["tool"] == "compose_video" else inputs
        return [source for parent in refs(values) for source in sources(parent, (*ancestors, node_id))]
    pending = [item["node_id"] for item in plan.get("deliverables", []) if item["kind"] in {"video", "package"}]
    visited = set()
    while pending:
        node_id = pending.pop(0)
        if node_id in visited:
            continue
        visited.add(node_id)
        node = nodes[node_id]
        if node["tool"] == "compose_video":
            ordered = sources(node_id)
            require(ordered, "Delivered composition contains no generated video nodes")
            return ordered
        pending.extend(refs(node.get("inputs", {})))
    return [node["id"] for node in plan.get("nodes", []) if node["tool"] in VIDEO_TOOLS]


class Harness:
    def __init__(self, evaluation, worker, name, run_id):
        from mock_media import install
        self.eval, self.worker, self.name, self.run_id = evaluation, worker, name, run_id
        self.client = evaluation.app.test_client()
        self.media = install(evaluation.WORK / "mock-media.jsonl")
        self.media.label = name
        self.eval.METER.set_label(name)
        self.result = {"scenario": name, "run_id": run_id, "started_at": time.time(),
                       "status": "running", "state_sequence": [], "actions": [], "evidence": {},
                       "meter_before": self.eval.METER.snapshot(), "media_before": self.media.summary()}
        self.path = evaluation.HERE / f"hybrid_{name}_{run_id or uuid.uuid4().hex[:8]}.json"

    def row(self):
        from app.extensions import db
        from app.models import AgentRun
        db.session.expire_all()
        return AgentRun.query.filter_by(run_id=self.run_id).one()

    def view(self):
        response = self.client.get(f"/api/agent/runs/{self.run_id}")
        require(response.status_code == 200, f"Read Run failed: HTTP {response.status_code}")
        return response.json["data"]

    def version(self):
        from app.agent.plan_versions import current_version
        return current_version(self.row()).version

    def observe(self):
        view = self.view()
        state = {"status": view["status"], "version": (view.get("plan") or {}).get("plan_version"),
                 "nodes": [{k: node.get(k) for k in ("node_id", "status", "gate_approved", "error")}
                           for node in view.get("nodes", [])],
                 "patches": [{k: patch.get(k) for k in ("patch_id", "status", "auto_approved", "approved_version")}
                             for patch in view.get("patches", [])], "error": view.get("error")}
        previous = self.result["state_sequence"][-1] if self.result["state_sequence"] else None
        if previous is None or previous["fingerprint"] != digest(state):
            self.result["state_sequence"].append({"at": time.time(), "fingerprint": digest(state), **state})
            self.save()
        return view

    def action(self, action, *, expected=(200, 202), **body):
        payload = {"action": action, "request_key": uuid.uuid4().hex, **body}
        response = self.client.post(f"/api/agent/runs/{self.run_id}/actions", json=payload)
        self.result["actions"].append({"payload": payload, "http_status": response.status_code,
                                       "error": (response.json or {}).get("error")})
        self.save()
        require(response.status_code in expected, f"{action} rejected: HTTP {response.status_code}: {(response.json or {}).get('error')}")
        return response

    def advance(self):
        from app.extensions import db
        self.worker.advance(self.run_id)
        db.session.remove()
        return self.observe()

    def gates(self, view, choice_index=None):
        for node in view.get("nodes", []):
            if node.get("gate_approved"):
                continue
            if node.get("gate") == "preview" and node["status"] == "success":
                self.action("approve_gate", plan_version=self.version(), gate_node_id=node["node_id"])
                return True
            if node.get("gate") == "choice" and (node.get("choice") or {}).get("ready"):
                if choice_index is None:
                    return False
                choice = node["choice"]
                require(len(choice["candidates"]) > choice_index, "The requested candidate does not exist")
                selected = choice["candidates"][choice_index]["artifact_id"]
                self.result["evidence"].setdefault("choices", []).append({"version": self.version(),
                    "node_id": node["node_id"], "choice_digest": choice["choice_digest"],
                    "candidates": [item["artifact_id"] for item in choice["candidates"]], "selected": selected})
                self.action("approve_gate", plan_version=self.version(), gate_node_id=node["node_id"],
                            selected_artifact_id=selected, choice_digest=choice["choice_digest"])
                return True
        return False

    def drive(self, *, stop=("awaiting_result_review",), preview=True, choice_index=None, max_ticks=240):
        started = time.monotonic()
        stable = 0
        previous = None
        unchanged_since = time.monotonic()
        for _ in range(max_ticks):
            view = self.observe()
            if view["status"] in stop and not view.get("action_pending"):
                return view
            if view.get("action_pending"):
                self.advance()
                time.sleep(0.15)
                continue
            if view["status"] in {"success", "failed", "cancelled", "awaiting_input"}:
                raise ScenarioFailure(f"Unexpected terminal/user state: {view['status']}: {view.get('error')}")
            pending_patch = [patch for patch in view.get("patches", []) if patch["status"] == "awaiting_approval"]
            if pending_patch:
                if "patch_approval" in stop:
                    return view
                raise ScenarioFailure("Manual Patch approval required; automatic continuation did not occur")
            if preview and self.gates(view, choice_index):
                self.advance()
                continue
            if view["status"] == "awaiting_gate" and any((node.get("choice") or {}).get("ready") and
                    not node.get("gate_approved") for node in view.get("nodes", [])) and choice_index is None:
                if "choice" in stop:
                    return view
                raise ScenarioFailure("A choice gate requires an explicit selection")
            fingerprint = digest({"status": view["status"], "nodes": view.get("nodes"),
                                  "agents": view.get("agents"), "patches": view.get("patches"), "error": view.get("error")})
            stable = stable + 1 if fingerprint == previous else 0
            if fingerprint != previous:
                unchanged_since = time.monotonic()
            previous = fingerprint
            active_jobs = any(node["status"] == "running" for node in view.get("nodes", []))
            if not active_jobs and view["status"] == "attention":
                require(time.monotonic() - unchanged_since < 15,
                        f"No progress in attention for 15 seconds: {view.get('error')}")
            require(time.monotonic() - started <= 1200, "Hybrid scenario exceeded 1200 seconds")
            self.advance()
            time.sleep(0.15)
        raise ScenarioFailure(f"Hybrid scenario exceeded {max_ticks} ticks")

    def approve_plan(self, repair_credits=0):
        require(self.view()["status"] == "awaiting_plan_review", "Source Run must be a real unapproved V10a plan")
        self.result["evidence"]["source_plan"] = deepcopy(self.view()["plan"])
        self.result["evidence"]["source_planning_delegations"] = deepcopy(self.view()["agents"])
        self.action("approve_plan", plan_version=self.version(), repair_budget_credits=repair_credits)

    def tasks(self):
        from app.models import PlanNodeTask
        return {task.node_id: {key: deepcopy(getattr(task, key)) for key in
            ("id", "plan_version", "node_id", "status", "inputs_hash", "inputs", "output", "state", "invocation_id", "job_id", "estimated_cost", "error")}
            for task in PlanNodeTask.query.filter_by(run_id=self.run_id, plan_version=self.version()).all()}

    def generation_receipts(self):
        from app.models import ToolInvocation
        return {row.invocation_id for row in ToolInvocation.query.filter(
            ToolInvocation.budget_scope == self.run_id,
            ToolInvocation.tool_name.in_(GENERATION_TOOLS), ToolInvocation.status != "rejected").all()}

    def quotes(self, patch_id, scope):
        response = self.client.post(f"/api/agent/runs/{self.run_id}/patch-quote", json={"patch_id": patch_id, "scope": scope})
        require(response.status_code == 200, f"Patch quote rejected: HTTP {response.status_code}: {response.json}")
        value = response.json["data"]
        self.result["evidence"].setdefault("quotes", []).append(deepcopy(value))
        self.save()
        return value

    def pending_patch(self, scope="cascade"):
        view = self.drive(stop=("patch_approval",), preview=True)
        patch = next(item for item in view["patches"] if item["status"] == "awaiting_approval")
        quote = self.quotes(patch["patch_id"], scope)
        require(quote["can_apply"] and quote["manual_can_apply"], f"Patch cannot execute: {quote.get('issues')}")
        return patch, quote

    def approve_quoted_patch(self, patch, quote):
        require(patch["patch_id"] == quote["patch_id"], "Patch and quote identities differ")
        self.action("approve_patch", patch_id=patch["patch_id"], quote_id=quote["quote_id"], scope=quote["scope"])

    def finish_delivery(self):
        view = self.drive()
        self.result["evidence"]["review_b"] = {"version": self.version(), "results": view.get("results"), "nodes": view["nodes"]}
        self.action("approve_results", plan_version=self.version())
        self.advance()
        require(self.view()["status"] == "success", "Run did not reach success after result approval")
        for result in self.view().get("results", []):
            response = self.client.get(result["download_url"])
            require(response.status_code == 200 and response.data, "Delivered artifact is not downloadable")
            self.result["evidence"].setdefault("downloads", []).append({"artifact_id": result["artifact_id"],
                "kind": result["kind"], "bytes": len(response.data), "sha256": hashlib.sha256(response.data).hexdigest()})

    def save(self):
        save_json(self.path, self.result)

    def close(self, failure=None):
        from app.models import AgentDelegation, ToolInvocation
        counters = self.eval.METER.snapshot()
        media_counters = self.media.summary()
        safety_counts = {"real_image_calls": counters.get("real_image_calls", 0),
            "real_video_calls": counters.get("real_video_calls", 0),
            "actual_real_media_http_calls": media_counters["actual_real_media_http_calls"],
            "blocked_media_attempts": counters.get("blocked_media_attempts", 0),
            "blocked_network_attempts": counters.get("blocked_network_attempts", 0),
            "real_media_adapter_attempts": media_counters["real_media_adapter_attempts"]}
        try:
            require(all(value == 0 for value in safety_counts.values()),
                    f"V10 media/network safety counter assertion failed: {safety_counts}")
        except ScenarioFailure as error:
            failure = failure or error
        self.result["safety_assertions"] = {"counts": safety_counts, "passed": all(value == 0 for value in safety_counts.values())}
        self.result.update(status="failed" if failure else "passed", finished_at=time.time(),
                           meter_after=self.eval.METER.snapshot(), media_after=self.media.summary())
        if failure:
            self.result["failure"] = {"type": type(failure).__name__, "message": str(failure)}
        if self.run_id:
            self.result["final_view"] = self.view()
            self.result["tasks"] = self.tasks() if self.view().get("plan") else {}
            self.result["patch_records"] = deepcopy((self.row().snapshot or {}).get("v3_patches", {}))
            self.result["repair_flows"] = deepcopy((self.row().snapshot or {}).get("v3_repair_flows", {}))
            self.result["delegations"] = [{"id": item.id, "parent_id": item.parent_id, "agent": item.agent,
                "status": item.status, "steps": item.steps, "llm_calls": item.llm_calls, "error": item.error}
                for item in AgentDelegation.query.filter_by(run_id=self.run_id).order_by(AgentDelegation.id)]
            self.result["ledger"] = [{"id": item.id, "invocation_id": item.invocation_id, "tool": item.tool_name,
                "key": item.idempotency_key, "status": item.status, "credits": item.estimated_cost,
                "delegation_id": item.delegation_id, "agent": item.caller_agent, "error_code": item.error_code,
                "usage": (item.output_payload or {}).get("usage"), "input_hash": digest(item.input_payload)}
                for item in ToolInvocation.query.filter_by(budget_scope=self.run_id).order_by(ToolInvocation.id)]
        self.save()
        print(json.dumps({"scenario": self.name, "status": self.result["status"], "report": str(self.path),
                          "failure": self.result.get("failure")}, ensure_ascii=False), flush=True)
        return self.result


def delivery(harness):
    """Approve c3, all preview gates, result review and actual local downloads."""
    tools = {node["tool"] for node in harness.view()["plan"]["nodes"]}
    require({"compose_video", "qc_video", "package_story"} <= tools, "Source c3 plan lacks compose/QC/package delivery stages")
    harness.approve_plan()
    harness.finish_delivery()
    require(any(item["kind"] == "package" for item in harness.result["evidence"].get("downloads", [])),
            "Full c3 delivery did not expose a downloadable package")


def story(harness):
    """Independent c3 trajectory for review-B user revision and delivery."""
    harness.approve_plan()
    view = harness.drive()
    require(len([node for node in view["nodes"] if node["tool"] in VIDEO_TOOLS]) >= 3, "Story needs at least three video nodes")
    before = harness.tasks()
    videos = ordered_video_nodes(view["plan"])
    require(len(videos) >= 3, "Delivered story needs at least three timeline clips")
    target = videos[2]
    before_receipts = harness.generation_receipts()
    harness.result["evidence"]["first_review_b"] = {"version": harness.version(), "tasks": before, "results": view["results"]}
    harness.action("revise_plan", plan_version=harness.version(),
        message=f"把第3镜（节点 {target}）改成雨夜，保持其他镜头和原时长、角色不变。请只重做必要的受影响子图，先报价由我批准。")
    patch, quote = harness.pending_patch("cascade")
    require(not quote["automatic"]["eligible"], "User revision must not be automatically authorized")
    require(target in quote["affected_node_ids"], "Director did not target the requested third shot")
    from app.models import AgentPlanVersion
    from story_scope import audit_story_patch_scope
    base = AgentPlanVersion.query.filter_by(run_id=harness.run_id, version=quote["base_version"]).one()
    record = harness.row().snapshot["v3_patches"][patch["patch_id"]]
    harness.result["evidence"]["scope_before_approval"] = audit_story_patch_scope(base.plan, record, quote, target)
    harness.save()
    harness.approve_quoted_patch(patch, quote)
    harness.drive()
    after = harness.tasks()
    actual_new_generations = {key for key, value in after.items() if value["state"].get("tool") in GENERATION_TOOLS
                              and value["invocation_id"] != before.get(key, {}).get("invocation_id")}
    quoted_generations = {key for key in quote["execute_node_ids"] if after[key]["state"].get("tool") in GENERATION_TOOLS}
    require(actual_new_generations == quoted_generations, "Actual redo differs from the approved affected subgraph")
    require(harness.generation_receipts() - before_receipts ==
            {after[key]["invocation_id"] for key in quoted_generations},
            "New generation ledger rows differ from the approved executed nodes")
    for key in quote["reused_node_ids"]:
        require(all(after[key][field] == before[key][field]
                    for field in ("inputs_hash", "inputs", "output", "invocation_id", "job_id")),
                f"Unaffected task provenance changed: {key}")
    harness.result["evidence"]["revision"] = {"target": target, "patch_id": patch["patch_id"],
        "actual_new_generation_nodes": sorted(actual_new_generations), "unaffected_reused": quote["reused_node_ids"]}
    harness.finish_delivery()


def fault(harness, automatic):
    view = harness.view()
    target = next(node for node in view["plan"]["nodes"] if node["tool"] in VIDEO_TOOLS)
    model, prompt = target["model_id"], target["inputs"]["prompt"]
    harness.media.arm(model, prompt, run_id=harness.run_id, node_id=target["id"])
    harness.approve_plan(repair_credits=30 if automatic else 0)
    if automatic:
        harness.drive()
    else:
        patch, quote = harness.pending_patch("only")
        require(not quote["automatic"]["eligible"], "Zero repair allowance unexpectedly permitted automatic repair")
        require("REPAIR_BUDGET_EXCEEDED" in quote["automatic"]["reasons"], "Manual path was not caused by the intended allowance constraint")
        harness.approve_quoted_patch(patch, quote)
        harness.drive()
    records = list((harness.row().snapshot or {}).get("v3_patches", {}).values())
    applied = [item for item in records if item.get("status") == "applied"]
    require(len(applied) == 1, "Expected exactly one reviewed, applied failure Patch")
    record = applied[0]
    require(record["approval"]["automatic"] is automatic, "Patch approval authority did not match the test")
    require(record["proposed_by"] == "repair" and record["director_review"]["verdict"] == "approve", "Repair/Director evidence incomplete")
    from app.models import ToolInvocation
    calls = ToolInvocation.query.filter_by(budget_scope=harness.run_id, tool_name="agent_llm_turn", status="success").all()
    require(any(row.caller_agent == "repair" for row in calls) and any(row.caller_agent == "director" for row in calls),
            "Repair and Director must both use real LLM turns")
    require(harness.media.failure is None, "The selected Mock video never received the injected failure")
    harness.result["evidence"]["failure_target"] = target["id"]
    harness.finish_delivery()


def choice(harness):
    harness.approve_plan()
    harness.drive(choice_index=1)
    first_choice = harness.result["evidence"]["choices"][-1]
    before = harness.tasks()
    videos = [value for value in before.values() if value["state"].get("tool") == "animate_shot"]
    require(videos and all(value["inputs"]["first_frame_artifact_id"] == first_choice["selected"] for value in videos),
            "Animation does not use the second selected candidate")
    harness.action("approve_gate", expected=(409,), plan_version=harness.version(), gate_node_id=first_choice["node_id"],
        selected_artifact_id=first_choice["candidates"][2], choice_digest=first_choice["choice_digest"])
    harness.action("revise_plan", plan_version=harness.version(),
        message="我想改选第3张候选，请重新打开选择门并在我明确确认后仅重做动画，保持3张候选图和原动画时长不变。请先给出修改报价。")
    patch, quote = harness.pending_patch("cascade")
    require(first_choice["node_id"] in quote["execute_node_ids"], "Reselection Patch did not reopen the original choice gate")
    require(not any(before.get(key, {}).get("state", {}).get("tool") == "generate_image"
                    for key in quote["execute_node_ids"]), "Reselection quote unexpectedly regenerates candidate images")
    harness.approve_quoted_patch(patch, quote)
    view = harness.drive(stop=("choice",), choice_index=None)
    pending = next(node for node in view["nodes"] if (node.get("choice") or {}).get("ready") and not node.get("gate_approved"))
    require(pending["choice"]["selected_artifact_id"] is None, "Old choice approval incorrectly survived the reselection Patch")
    require(harness.version() > first_choice["version"] and pending["choice"]["choice_digest"] != first_choice["choice_digest"],
            "Reselection did not receive a new version-bound proof")
    harness.action("approve_gate", expected=(409,), plan_version=first_choice["version"], gate_node_id=pending["node_id"],
        selected_artifact_id=first_choice["candidates"][2], choice_digest=first_choice["choice_digest"])
    harness.drive(choice_index=2)
    selected = harness.result["evidence"]["choices"][-1]["selected"]
    require(selected == first_choice["candidates"][2], "Candidate identities changed during pure reselection")
    after = harness.tasks()
    require(all(value["inputs"]["first_frame_artifact_id"] == selected for value in after.values()
                if value["state"].get("tool") == "animate_shot"), "Reselected animation did not use the third image")
    for key, value in before.items():
        if value["state"].get("tool") == "generate_image":
            require(after[key]["output"] == value["output"], "Reselection unnecessarily regenerated a candidate")
    harness.result["evidence"]["reselection_quote"] = quote
    harness.finish_delivery()


def crash_child(evaluation, run_id, marker):
    """Stop between durable paid receipt and Agent/checkpoint progress."""
    from app.tools.registry import ToolRegistry
    from app.models import ToolInvocation
    evaluation.METER.set_label("V10b-crash")
    original = ToolRegistry.invoke
    def pause(self, name, data, ctx):
        value = original(self, name, data, ctx)
        if name == "agent_llm_turn" and not value["replayed"]:
            row = ToolInvocation.query.filter_by(invocation_id=value["invocation_id"]).one()
            save_json(marker, {"run_id": run_id, "invocation_id": row.invocation_id,
                "key": row.idempotency_key, "status": row.status, "credits": row.estimated_cost,
                "input_hash": digest(row.input_payload), "output_hash": digest(row.output_payload),
                "meter": evaluation.METER.snapshot()})
            while True:
                time.sleep(0.25)
        return value
    ToolRegistry.invoke = pause
    from app.agent.worker import AgentWorker, worker_lock
    from langgraph.checkpoint.sqlite import SqliteSaver
    with evaluation.app.app_context(), worker_lock(), SqliteSaver.from_conn_string(os.environ["AGENT_CHECKPOINT_PATH"]) as saver:
        AgentWorker(None, None, v3_saver=saver).advance(run_id)
    raise ScenarioFailure("Worker did not reach the intended committed-LLM crash boundary")


def crash(harness):
    from app.extensions import db
    from app.models import ToolInvocation
    response = harness.client.post("/api/agent/runs", json={"text": harness.eval.CASES["c2_clip"]["text"],
                    "budget_limit": 100, "request_key": uuid.uuid4().hex})
    require(response.status_code in (200, 201, 202), "Crash test Run admission failed")
    harness.run_id = response.json["data"]["run_id"]
    harness.result["run_id"] = harness.run_id
    marker = harness.eval.WORK / f"crash-{harness.run_id}.json"
    db.session.remove()
    log_path = marker.with_suffix(".log")
    environment = dict(os.environ)
    process = None
    try:
        with log_path.open("w", encoding="utf-8") as log:
            process = subprocess.Popen([sys.executable, str(Path(__file__).resolve()), "crash-child", "--run-id", harness.run_id,
                                        "--marker", str(marker)], env=environment, stdout=log, stderr=log)
            deadline = time.monotonic() + 300
            while not marker.exists() and process.poll() is None and time.monotonic() < deadline:
                time.sleep(0.25)
            require(marker.exists(), f"Child did not reach committed-turn marker; log: {log_path.name}")
            frozen = json.loads(marker.read_text(encoding="utf-8"))
            process.kill()
            process.wait(timeout=20)
        require(frozen["status"] == "success", "Crash marker preceded durable settlement")
        harness.result["evidence"]["crash_window"] = "LLM ledger committed; Agent state/checkpoint not advanced; OS process forcibly killed once"
        harness.result["evidence"]["crash_receipt"] = frozen
        before_meter = harness.eval.METER.snapshot()
        # The first restarted graph step must replay this same paid turn.
        from app.agent.worker import worker_lock
        with worker_lock():
            harness.advance()
        after_meter = harness.eval.METER.snapshot()
        require(before_meter["real_calls"] == after_meter["real_calls"], "The first recovery tick made an extra physical model call")
        rows = ToolInvocation.query.filter_by(idempotency_key=frozen["key"]).all()
        require(len(rows) == 1 and rows[0].status == "success", "Recovery duplicated or lost the paid receipt")
        row = rows[0]
        require(row.estimated_cost == frozen["credits"] and digest(row.input_payload) == frozen["input_hash"]
                and digest(row.output_payload) == frozen["output_hash"], "Recovery changed the settled receipt")
        with worker_lock():
            harness.drive(stop=("awaiting_plan_review",), preview=False)
        harness.result["evidence"]["recovery"] = {"same_paid_receipt": True, "first_tick_physical_calls": 0,
            "new_planning_rounds_after_replay_allowed": True, "inflight_http_crash_not_tested": True}
    finally:
        if process is not None and process.poll() is None:
            process.kill()
            process.wait(timeout=20)


def load_evaluation():
    require(os.environ.get("EVAL_MOCK_MEDIA") == "1", "V10b requires EVAL_MOCK_MEDIA=1 before imports")
    import eval_v3 as evaluation
    from app.services.job_run_service import JobRunService
    from mock_media import install
    install(evaluation.WORK / "mock-media.jsonl")
    # Synchronous deterministic dispatch retains Job/Registry/Plan checks and avoids Redis.
    JobRunService.start = JobRunService.run_inline
    evaluation.app.config.update(AGENT_WORKER_ACTIVE=True, MQ_ENABLED=False, JOB_QUEUE_ENABLED=False)
    return evaluation


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("scenario", choices=["delivery", "story", "failure-auto", "failure-manual", "choice", "crash", "crash-child"])
    parser.add_argument("--run-id")
    parser.add_argument("--marker")
    args = parser.parse_args()
    evaluation = load_evaluation()
    if args.scenario == "crash-child":
        require(args.run_id and args.marker, "Crash child needs a Run and marker")
        return crash_child(evaluation, args.run_id, args.marker)
    require(args.run_id or args.scenario == "crash", "Reuse a V10a Run explicitly with --run-id")
    from app.agent.worker import AgentWorker, worker_lock
    from langgraph.checkpoint.sqlite import SqliteSaver
    with evaluation.app.app_context(), SqliteSaver.from_conn_string(os.environ["AGENT_CHECKPOINT_PATH"]) as saver:
        worker = AgentWorker(None, None, v3_saver=saver)
        harness = Harness(evaluation, worker, "V10b-" + args.scenario, args.run_id)
        failure = None
        try:
            # The child owns the OS lock during its kill window; parent owns it on ordinary paths.
            if args.scenario == "crash":
                crash(harness)
            else:
                with worker_lock():
                    if args.scenario == "delivery":
                        delivery(harness)
                    elif args.scenario == "story":
                        story(harness)
                    elif args.scenario == "choice":
                        choice(harness)
                    else:
                        fault(harness, args.scenario == "failure-auto")
        except Exception as error:
            failure = error
        finally:
            result = harness.close(failure)
        if result["status"] != "passed":
            raise SystemExit(1)


if __name__ == "__main__":
    main()
