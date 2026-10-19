"""V-Gate3 real-LLM evaluation of Agent v3 planning (D-030).

Isolation and spend guards:
- dotenv auto-loading is disabled; only DashScope credentials/URLs are read from the
  root .env (never printed). Everything else is set explicitly here.
- temp SQLite + storage; MQ off; auth off (owner "local").
- every video adapter's submit() raises: video generation is impossible in this process.
- image generation is capped process-wide (IMAGE_CAP); plans are never approved.
Usage (conda video-factory; PDF tests need pypdf on PYTHONPATH):
  python backend/scripts/v3_eval/eval_v3.py <case_id> [...] | all   (EVAL_V2=1 for the v2 baseline)
Results land in %TEMP%/cinecrew_v3_eval/results (or cinecrew_v2_eval). Real calls follow D-030.
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
WORK = Path(tempfile.gettempdir()) / ("cinecrew_v2_eval" if os.environ.get("EVAL_V2") else "cinecrew_v3_eval")
WORK.mkdir(parents=True, exist_ok=True)
HERE = WORK / "results"
HERE.mkdir(exist_ok=True)
IMAGE_CAP = int(os.environ.get("EVAL_IMAGE_CAP", "4"))
TEXT_MODEL, VISION_MODEL = "deepseek-v4.1-flash", "qwen3.7-plus"

import dotenv  # noqa: E402
secrets = dotenv.dotenv_values(ROOT / ".env")
dotenv.load_dotenv = lambda *a, **k: False  # nothing else from .env may leak in
os.environ.update({
    "DASHSCOPE_API_KEY": secrets.get("DASHSCOPE_API_KEY") or "",
    "DASHSCOPE_API_BASE_URL": secrets.get("DASHSCOPE_API_BASE_URL") or "https://dashscope.aliyuncs.com/api/v1",
    "DASHSCOPE_OPENAI_BASE_URL": secrets.get("DASHSCOPE_OPENAI_BASE_URL") or "https://dashscope.aliyuncs.com/compatible-mode/v1",
    "DEEPSEEK_API_KEY": "", "OPENAI_API_KEY": "",
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
assert os.environ["DASHSCOPE_API_KEY"], "DASHSCOPE_API_KEY missing in root .env"
sys.path.insert(0, str(BACKEND))
os.chdir(BACKEND)

from app import create_app  # noqa: E402

app = create_app("development")

# ---- spend guards -------------------------------------------------------
from app.adapters import dashscope_i2v, dashscope_r2v, dashscope_t2v, dashscope_wan3  # noqa: E402


def _blocked(self, payload):
    raise RuntimeError("VIDEO GENERATION BLOCKED IN V-GATE3 EVAL (D-030)")


for cls in (dashscope_i2v.DashScopeI2VAdapter, dashscope_r2v.DashScopeR2VFlashAdapter,
            dashscope_t2v.DashScopeT2VAdapter, dashscope_wan3.DashScopeWan3Adapter):
    cls.submit = _blocked

from app.adapters import dashscope_image, dashscope_qwen_image  # noqa: E402
IMAGE_CALLS = []
for cls in (dashscope_image.DashScopeImageAdapter, dashscope_qwen_image.DashScopeQwenImageAdapter):
    original = cls.submit

    def guarded(self, payload, _original=original, _name=cls.__name__):
        if len(IMAGE_CALLS) >= IMAGE_CAP:
            raise RuntimeError("IMAGE CAP REACHED IN V-GATE3 EVAL")
        IMAGE_CALLS.append(_name)
        return _original(self, payload)
    cls.submit = guarded

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
    answered = 0
    for _ in range(400):
        worker.tick()
        from app.extensions import db
        db.session.remove()
        view = client.get(f"/api/agent/runs/{run_id}").json["data"]
        status = view["status"]
        if status == "awaiting_input" and case_id != "c4_vague" and answered < 1 and view.get("pending_card"):
            card = view["pending_card"]
            notes.append({"question_card": [q.get("text") for q in card.get("questions", [])]})
            r = client.post(f"/api/agent/runs/{run_id}/actions", json={"action": "answer", "card_id": card["card_id"], "use_defaults": True})
            notes.append({"answered_with_defaults": r.status_code})
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
    return {
        "case": case_id, "purpose": case["purpose"], "run_id": run_id, "status": view["status"],
        "elapsed_sec": round(elapsed, 1), "notes": notes,
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
        app.test_cli_runner().invoke(args=["init-db"])
        app.config["FAILURE_AGENT_ENABLED"] = False
        app.config["AGENT_WORKER_ACTIVE"] = True
        client = app.test_client()
        with SqliteSaver.from_conn_string(os.environ["AGENT_CHECKPOINT_PATH"]) as saver:
            worker = AgentWorker(build_graph(saver), build_graph_v2(saver), v3_saver=saver)
            for case_id in ids:
                result = run_case(client, worker, case_id, CASES[case_id])
                result["image_generation_calls_so_far"] = len(IMAGE_CALLS)
                out = HERE / (f"v2_result_{case_id}.json" if os.environ.get("EVAL_V2") else f"result_{case_id}.json")
                out.write_text(json.dumps(result, ensure_ascii=False, indent=2, default=str), encoding="utf-8")
                print(json.dumps({k: result[k] for k in ("case", "status", "elapsed_sec", "spent_total")}, ensure_ascii=False), flush=True)


if __name__ == "__main__":
    args = sys.argv[1:] or ["c2_clip"]
    main(list(CASES) if args == ["all"] else args)
