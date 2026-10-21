"""V10 real-LLM evaluation of Agent v3 planning (D-030).

Isolation and spend guards:
- dotenv auto-loading is disabled; only allowlisted DashScope credential lines
  can be read (never printed). Database/Redis values are never parsed.
- temp SQLite + storage; MQ off; auth off (owner "local").
- every video adapter's submit() raises: video generation is impossible in this process.
- all image/video generation is blocked; durable HTTP reservations cap the whole round at 800.
Usage (conda video-factory; PDF tests need pypdf on PYTHONPATH):
  python backend/scripts/v3_eval/eval_v3.py <case_id> [...] | all   (EVAL_V2=1 for the v2 baseline)
Results land in EVAL_WORK_DIR/results (default %TEMP%/cinecrew-v10). Real calls follow D-030.
"""
import json
import os
import sys
import tempfile
import time
import uuid
from pathlib import Path

ROOT = Path(__file__).resolve().parents[3]
BACKEND = ROOT / "backend"
WORK = Path(os.environ.get("EVAL_WORK_DIR") or (Path(tempfile.gettempdir()) / "cinecrew-v10"))
WORK.mkdir(parents=True, exist_ok=True)
HERE = WORK / "results"
HERE.mkdir(exist_ok=True)
from safety import configure_environment, install_guards
from metrics import delegation_tree, history_issues, issue_codes, plan_metrics, summarize_turns
from eval_actions import answer_defaults

TEXT_MODEL, VISION_MODEL = "deepseek-v4.1-flash", "qwen3.7-plus"
configure_environment(ROOT, WORK)
os.environ.update({
    "DATABASE_URL": f"sqlite:///{(WORK / 'eval.db').as_posix()}",
    "STORAGE_ROOT": str(WORK / "storage"), "UPLOAD_FOLDER": str(WORK / "storage" / "uploads"),
    "MODEL_ADAPTER_MODE": "real", "MQ_ENABLED": "false", "JOB_QUEUE_ENABLED": "true",
    "API_AUTH_REQUIRED": "false", "AGENT_MODE_ENABLED": "true", "AGENT_V3_ENABLED": "false" if os.environ.get("EVAL_V2") else "true",
    "AGENT_ACCEPT_NEW_RUNS": "true", "AGENT_ALLOWED_USERS": "", "AGENT_MAX_BUDGET": "500",
    "AGENT_DEFAULT_BUDGET": "100", "AGENT_AUTO_APPROVE_CREDITS": "0",
    "AGENT_PLANNER_MODEL": TEXT_MODEL, "AGENT_V3_DEFAULT_TEXT_MODEL": TEXT_MODEL,
    "AGENT_V3_DEFAULT_VISION_MODEL": VISION_MODEL, "AGENT_VISION_MODEL": VISION_MODEL,
    **{f"AGENT_{role}_MODEL": TEXT_MODEL for role in (
        "PRODUCER", "RESEARCH", "CREATIVE", "DIRECTOR", "PROMPT_SMITH", "CRITIC", "REPAIR", "INTAKE")},
    "AGENT_SEARCH_PROVIDER": "mock", "AGENT_STORY_V2_ENABLED": "true",
    "AGENT_STORY_PRODUCTION_ENABLED": "false", "AGENT_STORY_DELIVERY_ENABLED": "false",
    "AGENT_CHECKPOINT_PATH": str(WORK / "checkpoints.sqlite"), "AGENT_POLL_INTERVAL_SEC": "0.2",
    "FAILURE_AGENT_ENABLED": "false", "VIDEO_COMPRESSION_ENABLED": "false",
})
assert os.environ["DASHSCOPE_API_KEY"], "DASHSCOPE_API_KEY missing"
sys.path.insert(0, str(BACKEND))
os.chdir(BACKEND)

from app import create_app  # noqa: E402

METER = install_guards(WORK)
app = create_app("development")

# ---- cases --------------------------------------------------------------
CASES = {
    "c1_portrait": {"text": "把这张头像改成正式的证件照：纯白背景，深色西装，正面构图", "attach": ["portrait.png"],
                    "purpose": "简单改图：应由 Producer 独立完成（不委派），一次多模态理解，产出单个 i2i 节点"},
    "c2_clip": {"text": "生成一段8秒的视频：一只橘猫在洒满阳光的窗台上跳舞",
                "purpose": "单镜头视频：无需 Creative/Research；时长 8 秒须符合模型时长与步长"},
    "c3_story": {"text": "做一个约2分钟的AI拟人短片：DeepSeek和ChatGPT两个拟人角色一起参加编程比赛，经历波折，最后握手言和",
                 "purpose": "长片：应委派 Director（必要时 Creative），多镜头总时长约120秒，角色一致性与预览门", "budget": 300},
    "c4_vague": {"text": "帮我做个视频",
                 "purpose": "信息不足：应向用户提出 1–3 个有意义的选择题，不直接产出计划"},
    "c5_novel": {"text": "先给我生成3张不同海报风格的猫咪图片，我从中选一张，再把选中的那张做成10秒动画",
                 "purpose": "非模板组合：图片多选预览门 + 后续图生视频，检验是否能灵活组合而非套用固定配方"},
    "c6_constraint": {"text": "做一段5秒的海浪拍打礁石的视频，必须用wan2.7系列模型，不要用happy-horse",
                      "purpose": "模型约束：所有视频节点必须是 wan2.7 系列且不得出现 happy-horse"},
}
ACTIVE = {"queued", "understanding", "analyzing", "researching", "planning", "previewing", "executing"}


def make_portrait(path):
    from PIL import Image, ImageDraw
    img = Image.new("RGB", (768, 960), (196, 214, 230))
    d = ImageDraw.Draw(img)
    d.rectangle((0, 700, 768, 960), fill=(70, 110, 160))            # casual blue top
    d.ellipse((234, 180, 534, 540), fill=(238, 200, 170))           # face
    d.pieslice((214, 140, 554, 420), 180, 360, fill=(60, 40, 30))    # hair
    d.rectangle((334, 520, 434, 640), fill=(238, 200, 170))         # neck
    d.ellipse((310, 320, 340, 345), fill=(40, 40, 40)); d.ellipse((428, 320, 458, 345), fill=(40, 40, 40))
    d.arc((340, 400, 428, 460), 20, 160, fill=(150, 60, 60), width=5)
    img.save(path)


def run_case(client, worker, case_id, case):
    started, notes = time.time(), []
    METER.set_label(case_id)
    attachment_ids = []
    for name in case.get("attach", []):
        path = WORK / name
        if not path.exists():
            make_portrait(path)
        with path.open("rb") as handle:
            response = client.post("/api/agent/attachments", data={"file": (handle, name)}, content_type="multipart/form-data")
        assert response.status_code == 201, response.json
        attachment_ids.append(response.json["data"]["attachment_id"])
    response = client.post("/api/agent/runs", json={"text": case["text"], "budget_limit": case.get("budget", 100),
                                                   "attachment_ids": attachment_ids, "request_key": uuid.uuid4().hex})
    assert response.status_code in (200, 201, 202), response.json
    run_id = response.json["data"]["run_id"]
    METER.set_label(f"{case_id}:{run_id}")
    print(json.dumps({"event": "created", "case": case_id, "run_id": run_id}), flush=True)
    (HERE / f"active_{case_id}.json").write_text(json.dumps({"run_id": run_id, "started": started}), encoding="utf-8")
    answered = 0
    for _ in range(400):
        worker.advance(run_id)
        from app.extensions import db
        db.session.remove()
        view = client.get(f"/api/agent/runs/{run_id}").json["data"]
        status = view["status"]
        print(json.dumps({"event": "tick", "case": case_id, "status": status,
                          "elapsed_sec": round(time.time() - started, 1)}), flush=True)
        if status == "awaiting_input" and case_id != "c4_vague" and answered < 1 and view.get("pending_card"):
            card = view["pending_card"]
            notes.append({"question_card": [q.get("text") for q in card.get("questions", [])]})
            if not answer_defaults(client, run_id, card["card_id"], notes,
                                   v3=app.config.get("AGENT_V3_ENABLED", False)):
                break
            answered += 1
            continue
        if status not in ACTIVE:
            break
        if time.time() - started > 900:
            notes.append("TIMEOUT 900s")
            break
        time.sleep(0.2)
    return collect(client, run_id, case_id, case, time.time() - started, notes)


def collect(client, run_id, case_id, case, elapsed, notes):
    from app.models import AgentDelegation, AgentStep, ToolInvocation
    view = client.get(f"/api/agent/runs/{run_id}").json["data"]
    delegations = AgentDelegation.query.filter_by(run_id=run_id).order_by(AgentDelegation.id).all()
    steps = AgentStep.query.filter_by(run_id=run_id).order_by(AgentStep.id).all()
    ledger = ToolInvocation.query.filter_by(budget_scope=run_id).all()
    by_tool = {}
    for row in ledger:
        key = row.tool_name
        item = by_tool.setdefault(key, {"calls": 0, "credits": 0.0, "statuses": {}})
        item["calls"] += 1
        item["credits"] += row.estimated_cost or 0
        item["statuses"][row.status] = item["statuses"].get(row.status, 0) + 1
    plan = view.get("plan") or {}
    nodes = [{"id": n.get("id"), "tool": n.get("tool"), "model": n.get("model_id"),
              "duration": (n.get("params") or {}).get("duration"), "gate": n.get("gate"),
              "deps": n.get("depends_on"), "prompt": str((n.get("inputs") or {}).get("prompt", ""))[:160]}
             for n in plan.get("nodes", [])]
    metrics = summarize_turns(ledger)
    metrics.update(history_issues([row.state or {} for row in delegations]))
    return {
        "case": case_id, "purpose": case["purpose"], "run_id": run_id, "status": view["status"],
        "elapsed_sec": round(elapsed, 1), "notes": notes,
        "metrics": metrics, "delegation_tree": delegation_tree(delegations),
        "plan_metrics": plan_metrics(plan), "full_plan": plan,
        "final_compile_issue_codes": issue_codes(view.get("plan_issues")),
        "pending_questions": [q.get("text") for q in ((view.get("pending_card") or {}).get("questions") or [])],
        "delegations": [{"id": d.id, "parent": d.parent_id, "agent": d.agent, "status": d.status, "depth": d.depth,
                         "llm_calls": d.llm_calls, "steps": d.steps, "credits_limit": d.credits_limit,
                         "task": (d.task or "")[:200], "error": d.error,
                         "output_kind": (d.output or {}).get("kind") if isinstance(d.output, dict) else None,
                         "output": json.dumps(d.output, ensure_ascii=False)[:400] if d.output else None} for d in delegations],
        "tool_sequence": [f"{s.agent}:{s.kind}:{s.tool or ''}" for s in steps],
        "ledger_by_tool": by_tool,
        "spent_total": round(sum(r.estimated_cost or 0 for r in ledger if r.status != "rejected"), 4),
        "plan_title": plan.get("title"), "plan_nodes": nodes, "deliverables": plan.get("deliverables"),
        "experimental": view.get("experimental"), "plan_issues": view.get("plan_issues"),
        "estimates": view.get("estimates"), "planning_budget": view.get("planning_budget"),
        "error": view.get("error"),
        "raw_plan": json.dumps(plan, ensure_ascii=False)[:3000],
        "story_raw": json.dumps(view.get("story"), ensure_ascii=False)[:1500] if view.get("story") else None,
    }


def main(ids):
    from langgraph.checkpoint.sqlite import SqliteSaver
    from app.agent.graph import build_graph
    from app.agent.graph_v2 import build_graph as build_graph_v2
    from app.agent.worker import AgentWorker
    with app.app_context():
        initialized = app.test_cli_runner().invoke(args=["init-db"])
        assert initialized.exit_code == 0, initialized.output
        app.config["FAILURE_AGENT_ENABLED"] = False
        app.config["AGENT_WORKER_ACTIVE"] = True
        client = app.test_client()
        with SqliteSaver.from_conn_string(os.environ["AGENT_CHECKPOINT_PATH"]) as saver:
            worker = AgentWorker(build_graph(saver), build_graph_v2(saver), v3_saver=saver)
            for case_id in ids:
                if METER.snapshot()["real_calls"] >= METER.snapshot()["call_limit"]:
                    print(json.dumps({"event": "stopped", "reason": "V10_CALL_LIMIT", "safety": METER.snapshot()}), flush=True)
                    break
                result = run_case(client, worker, case_id, CASES[case_id])
                result["safety"] = METER.snapshot()
                out = HERE / f"result_{case_id}_{result['run_id']}.json"
                out.write_text(json.dumps(result, ensure_ascii=False, indent=2, default=str), encoding="utf-8")
                (HERE / f"result_{case_id}.json").write_text(out.read_text(encoding="utf-8"), encoding="utf-8")
                print(json.dumps({k: result[k] for k in ("case", "status", "elapsed_sec", "spent_total")}, ensure_ascii=False), flush=True)


if __name__ == "__main__":
    args = sys.argv[1:] or ["c2_clip"]
    main(list(CASES) if args == ["all"] else args)
