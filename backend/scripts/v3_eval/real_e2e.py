"""One-off real end-to-end v3 test authorized by the user (2026-10-22).

Real text/vision planning plus REAL image/video generation, capped hard:
video seconds <= 60 in total, images <= 14, video models wan2.7 only.
The image cap counts the requested n; a provider can still return more images
per request (wan2.6-image with enable_interleave did, see REAL_E2E_20261022.md).
Isolation: dotenv disabled, only allowlisted DashScope credentials, temp SQLite
and storage, MQ off, auth off. Every paid step waits for an explicit command
(plan approval, preview/choice gates, result approval), mirroring a real user.

Usage (conda video-factory):
  python real_e2e.py plan <task>          create + plan, stop at review
  python real_e2e.py show <run>
  python real_e2e.py approve-plan <run>
  python real_e2e.py go <run>             execute until the next human decision
  python real_e2e.py gate <run> <node> [candidate_index]
  python real_e2e.py approve-results <run>
  python real_e2e.py revise <run> <message>
  python real_e2e.py quote <run> [only|cascade]
  python real_e2e.py approve-patch <run> <scope>
  python real_e2e.py ledger
"""
import json
import os
import sys
import time
import uuid
from pathlib import Path

REPO = Path(os.environ["E2E_REPO"])
BACKEND = REPO / "backend"
WORK = Path(os.environ["E2E_WORK"])
WORK.mkdir(parents=True, exist_ok=True)
RESULTS = WORK / "results"
RESULTS.mkdir(exist_ok=True)
LEDGER = WORK / "media-ledger.json"
VIDEO_SECONDS_CAP = 60
IMAGE_CAP = 14
VIDEO_ADAPTERS = {"dashscope_t2v", "dashscope_i2v", "dashscope_r2v_flash", "dashscope_wan3"}
IMAGE_ADAPTERS = {"dashscope_image", "dashscope_multimodal_sync", "dashscope_qwen_image"}
TEXT_MODEL, VISION_MODEL = "deepseek-v4.1-flash", "qwen3.7-plus"

TASKS = {
    "t1_watertown": {
        "budget": 60,
        "text": ("生成一段约8秒的视频：清晨薄雾中的江南水乡，一只乌篷船从石拱桥下缓缓划过，船夫戴着斗笠，"
                 "两岸白墙黛瓦，水面泛着细碎的晨光，镜头平稳地跟随船只。画面比例16:9，画质720P即可，使用wan2.7系列模型。"),
        "purpose": "单镜头文生视频：比例 16:9、约 8 秒、wan2.7-t2v、720P；无需子委派",
    },
    "t2_neon_cat": {
        "budget": 80,
        "text": ("先生成3张不同画风的图片，主题是“雨夜霓虹街角，一只坐在纸箱上的小黑猫”，三种画风分别是水彩、赛博朋克、浮世绘，各一张。"
                 "我从中选一张，再把选中的那张做成约5秒的动画：雨丝落下，霓虹灯闪烁，小猫轻轻摇尾巴。"
                 "竖屏9:16，画质720P即可，全部使用wan2.7系列模型。"),
        "purpose": "三风格选图 + 图生视频：真实选择门、9:16、wan2.7-image + wan2.7-i2v",
    },
    "t2b_neon_cat": {
        "budget": 80,
        "text": ("先生成3张不同画风的图片，主题是“雨夜霓虹街角，一只坐在纸箱上的小黑猫”，三种画风分别是水彩、赛博朋克、浮世绘，各一张。"
                 "我从中选一张，再把选中的那张做成约5秒的动画：雨丝落下，霓虹灯闪烁，小猫轻轻摇尾巴。"
                 "竖屏9:16，画质720P即可。图片使用wan2.7-image模型，视频使用wan2.7-i2v模型。"),
        "purpose": "T2 重测：图片显式指定 wan2.7-image（绕开 wan2.6-image 交错输出缺陷），真实选择门 + 图生视频",
    },
    "t3_fox_lantern": {
        "budget": 150,
        "text": ("做一支约20秒的两镜头短片，画面比例16:9，画质720P即可。图片用wan2.7-image，视频用wan2.7-i2v。"
                 "主角是一只戴红色针织围巾的小狐狸，两个镜头里它的外形要保持一致。"
                 "镜头一：雪夜的森林里，小狐狸发现雪地上一盏发着暖光的纸灯笼，好奇地凑近闻了闻。"
                 "镜头二：小狐狸叼起灯笼，踩着积雪走向远处窗户亮着灯的小木屋。"),
        "purpose": "双镜头角色一致性：定妆 → 关键帧 → 图生视频 → 拼接与质检；约 20 秒；后续用于局部修改",
    },
}
TASKS["t3b_fox_lantern"] = {**TASKS["t3_fox_lantern"], "text": TASKS["t3_fox_lantern"]["text"].replace(
    "图片用wan2.7-image，视频用wan2.7-i2v。", "模型偏好：wan2.7-image、wan2.7-i2v。"),
    "purpose": "T3 重测：模型偏好写成独立的模型 ID 列表"}
ACTIVE = {"queued", "understanding", "analyzing", "researching", "planning", "previewing", "executing"}

# ---- isolation --------------------------------------------------------------
sys.path.insert(0, str(BACKEND / "scripts" / "v3_eval"))
from safety import configure_environment  # noqa: E402

# Credentials come from the main checkout's .env via the allowlist reader only.
configure_environment(Path(os.environ["E2E_ENV_ROOT"]), WORK)
os.environ.update({
    "MODEL_ADAPTER_MODE": "real", "MQ_ENABLED": "false", "JOB_QUEUE_ENABLED": "true",
    "API_AUTH_REQUIRED": "false", "AGENT_MODE_ENABLED": "true", "AGENT_V3_ENABLED": "true",
    "AGENT_ACCEPT_NEW_RUNS": "true", "AGENT_ALLOWED_USERS": "", "AGENT_MAX_BUDGET": "500",
    "AGENT_DEFAULT_BUDGET": "100", "AGENT_AUTO_APPROVE_CREDITS": "0",
    "AGENT_SEARCH_PROVIDER": "mock", "AGENT_STORY_V2_ENABLED": "true",
    "AGENT_STORY_PRODUCTION_ENABLED": "false", "AGENT_STORY_DELIVERY_ENABLED": "false",
    "AGENT_POLL_INTERVAL_SEC": "0.5", "FAILURE_AGENT_ENABLED": "false",
    "VIDEO_COMPRESSION_ENABLED": "false", "POLL_INTERVAL_SEC": "8", "MAX_POLL_ROUNDS": "120",
    "FFMPEG_BINARY": os.environ["E2E_FFMPEG"], "EVAL_IMAGE_CAP": str(IMAGE_CAP),
})
sys.path.insert(0, str(BACKEND))
os.chdir(BACKEND)
from app import create_app  # noqa: E402

app = create_app("development")


# ---- hard media caps ---------------------------------------------------------
def _ledger():
    if LEDGER.exists():
        return json.loads(LEDGER.read_text(encoding="utf-8"))
    return {"video_seconds": 0, "videos": 0, "images": 0, "submits": []}


def _guard(adapter_name, original):
    def submit(self, payload):
        model = str(payload.get("model") or self.model_id)
        params = payload.get("parameters") or {}
        book = _ledger()
        entry = {"at": time.strftime("%Y-%m-%d %H:%M:%S"), "adapter": adapter_name, "model": model}
        if adapter_name in VIDEO_ADAPTERS:
            seconds = int(params.get("duration") or 0)
            if not model.startswith("wan2.7"):
                raise RuntimeError(f"E2E guard: video model {model} is not wan2.7")
            if seconds <= 0 or book["video_seconds"] + seconds > VIDEO_SECONDS_CAP:
                raise RuntimeError(f"E2E guard: video cap ({book['video_seconds']}+{seconds} > {VIDEO_SECONDS_CAP}s)")
            book["video_seconds"] += seconds
            book["videos"] += 1
            entry.update(kind="video", seconds=seconds, resolution=params.get("resolution"),
                         ratio=params.get("ratio"), size=params.get("size"))
        else:
            count = int(params.get("n") or 1)
            if book["images"] + count > IMAGE_CAP:
                raise RuntimeError(f"E2E guard: image cap ({book['images']}+{count} > {IMAGE_CAP})")
            book["images"] += count
            entry.update(kind="image", count=count, size=params.get("size"))
        # Reserve before transport: a failed or unknown request still counts.
        book["submits"].append(entry)
        LEDGER.write_text(json.dumps(book, ensure_ascii=False, indent=1), encoding="utf-8")
        return original(self, payload)
    return submit


from app import adapters as _adapters  # noqa: E402

# Capture every original first so an inherited, already wrapped method is never wrapped twice.
_originals = {name: _adapters.ADAPTERS[name].submit for name in VIDEO_ADAPTERS | IMAGE_ADAPTERS}
for _name, _original in _originals.items():
    _adapters.ADAPTERS[_name].submit = _guard(_name, _original)

from app.services.job_run_service import JobRunService  # noqa: E402

JobRunService.start = JobRunService.run_inline  # synchronous, no Redis


# ---- helpers -----------------------------------------------------------------
def ctx():
    from langgraph.checkpoint.sqlite import SqliteSaver
    from app.agent.worker import AgentWorker
    saver_cm = SqliteSaver.from_conn_string(os.environ["AGENT_CHECKPOINT_PATH"])
    return saver_cm, AgentWorker


def view(client, run_id):
    response = client.get(f"/api/agent/runs/{run_id}")
    assert response.status_code == 200, response.json
    return response.json["data"]


def action(client, run_id, name, **body):
    payload = {"action": name, "request_key": uuid.uuid4().hex, **body}
    response = client.post(f"/api/agent/runs/{run_id}/actions", json=payload)
    print(json.dumps({"action": name, "http": response.status_code, "error": (response.json or {}).get("error")},
                     ensure_ascii=False))
    return response


def plan_version(data):
    return (data.get("plan") or {}).get("plan_version")


def artifact_path(artifact_id):
    from app.models import Artifact
    from app.services.storage_service import StorageService
    row = Artifact.query.filter_by(artifact_id=artifact_id).first()
    return str(StorageService.resolve(row.file_path)) if row else None


def summary(client, run_id):
    data = view(client, run_id)
    plan = data.get("plan") or {}
    nodes = []
    for node in plan.get("nodes", []):
        params = node.get("params") or {}
        inputs = node.get("inputs") or {}
        nodes.append({"id": node.get("id"), "tool": node.get("tool"), "model": node.get("model_id"),
            "gate": node.get("gate"), "characters": node.get("characters"),
            "params": {k: params.get(k) for k in ("duration", "resolution", "ratio", "size", "n") if k in params},
            "mode": inputs.get("mode"), "target_aspect_ratio": inputs.get("target_aspect_ratio"),
            "prompt": str(inputs.get("prompt", ""))[:220]})
    status_nodes = []
    for node in data.get("nodes", []):
        item = {k: node.get(k) for k in ("node_id", "status", "gate", "gate_approved", "error")}
        item["artifacts"] = [{"id": a["artifact_id"], "mime": a.get("mime_type"), "path": artifact_path(a["artifact_id"])}
                             for a in node.get("artifacts", [])]
        if node.get("choice"):
            item["choice"] = {"ready": node["choice"].get("ready"),
                "candidates": [{"artifact_id": c["artifact_id"], "path": artifact_path(c["artifact_id"])}
                               for c in node["choice"].get("candidates", [])]}
        status_nodes.append(item)
    out = {"run_id": run_id, "status": data["status"], "action_pending": data.get("action_pending"),
        "title": plan.get("title"), "goal": plan.get("goal"), "plan_version": plan_version(data),
        "duration_constraint": plan.get("duration_constraint"), "estimates": data.get("estimates"),
        "plan_issues": data.get("plan_issues"), "planning_budget": data.get("planning_budget"),
        "estimated_spent": data.get("estimated_spent"), "pending_card": data.get("pending_card"),
        "error": data.get("error"), "nodes": nodes, "node_status": status_nodes,
        "patches": [{k: p.get(k) for k in ("patch_id", "status", "reason", "scope")} for p in data.get("patches", [])],
        "results": [{"kind": r.get("kind"), "artifact_id": r["artifact_id"], "path": artifact_path(r["artifact_id"])}
                    for r in data.get("results", [])],
        "media_ledger": {k: v for k, v in _ledger().items() if k != "submits"}}
    (RESULTS / f"{run_id}.json").write_text(json.dumps({**out, "full_plan": plan}, ensure_ascii=False, indent=1,
                                                       default=str), encoding="utf-8")
    return out


def advance_until_human(client, worker, run_id, *, limit_sec=3600):
    from app.extensions import db
    started = time.time()
    last = None
    while time.time() - started < limit_sec:
        worker.advance(run_id)
        db.session.remove()
        data = view(client, run_id)
        state = (data["status"], data.get("action_pending"),
                 tuple((n["node_id"], n["status"]) for n in data.get("nodes", [])))
        if state != last:
            print(json.dumps({"t": round(time.time() - started), "status": data["status"],
                "nodes": {n["node_id"]: n["status"] for n in data.get("nodes", [])}}, ensure_ascii=False), flush=True)
            last = state
        if data.get("action_pending"):
            time.sleep(0.3)
            continue
        if any(p["status"] == "awaiting_approval" for p in data.get("patches", [])):
            return
        if data["status"] not in ACTIVE:
            return
        time.sleep(0.5)
    print(json.dumps({"event": "time_limit"}))


def main(argv):
    command, args = argv[0], argv[1:]
    with app.app_context():
        from app.extensions import db
        marker = WORK / "db-initialized"
        if not marker.exists():
            result = app.test_cli_runner().invoke(args=["init-db"])
            assert result.exit_code == 0, result.output
            marker.write_text("ok", encoding="utf-8")
        app.config["AGENT_WORKER_ACTIVE"] = True
        client = app.test_client()
        if command == "ledger":
            print(json.dumps(_ledger(), ensure_ascii=False, indent=1))
            return
        saver_cm, AgentWorker = ctx()
        with saver_cm as saver:
            worker = AgentWorker(None, None, v3_saver=saver)
            if command == "plan":
                task = TASKS[args[0]]
                response = client.post("/api/agent/runs", json={"text": task["text"], "budget_limit": task["budget"],
                    "attachment_ids": [], "request_key": uuid.uuid4().hex})
                assert response.status_code in (200, 201, 202), response.json
                run_id = response.json["data"]["run_id"]
                print(json.dumps({"created": run_id, "task": args[0]}), flush=True)
                advance_until_human(client, worker, run_id, limit_sec=1200)
                run = run_id
            else:
                run = args[0]
                version = plan_version(view(client, run))
                if command == "approve-plan":
                    action(client, run, "approve_plan", plan_version=version, repair_budget_credits=0)
                elif command == "go":
                    advance_until_human(client, worker, run)
                elif command == "gate":
                    data = view(client, run)
                    node = next(n for n in data["nodes"] if n["node_id"] == args[1])
                    body = {"plan_version": version, "gate_node_id": args[1]}
                    if node.get("gate") == "choice":
                        choice = node["choice"]
                        body.update(selected_artifact_id=choice["candidates"][int(args[2])]["artifact_id"],
                                    choice_digest=choice["choice_digest"])
                    action(client, run, "approve_gate", **body)
                elif command == "answer":
                    card = view(client, run)["pending_card"]
                    action(client, run, "answer", card_id=card["card_id"],
                           answers=[{"question_id": args[1], "text": args[2][5:]} if args[2].startswith("text:")
                                    else {"question_id": args[1], "option_id": args[2]}])
                    advance_until_human(client, worker, run, limit_sec=1200)
                elif command == "approve-results":
                    action(client, run, "approve_results", plan_version=version)
                    worker.advance(run)
                    db.session.remove()
                elif command == "revise":
                    action(client, run, "revise_plan", plan_version=version, message=args[1])
                    advance_until_human(client, worker, run, limit_sec=1200)
                elif command == "quote":
                    data = view(client, run)
                    patch = next(p for p in data["patches"] if p["status"] == "awaiting_approval")
                    scope = args[1] if len(args) > 1 else "only"
                    response = client.post(f"/api/agent/runs/{run}/patch-quote", json={"patch_id": patch["patch_id"], "scope": scope})
                    quote = response.json.get("data") or response.json
                    (RESULTS / f"{run}-quote-{scope}.json").write_text(json.dumps(quote, ensure_ascii=False, indent=1), encoding="utf-8")
                    print(json.dumps({k: quote.get(k) for k in ("patch_id", "quote_id", "scope", "can_apply", "manual_can_apply",
                        "estimated_credits", "execute_node_ids", "reused_node_ids", "retained_node_ids", "issues", "warnings")},
                        ensure_ascii=False, indent=1))
                    return
                elif command == "approve-patch":
                    scope = args[1]
                    quote = json.loads((RESULTS / f"{run}-quote-{scope}.json").read_text(encoding="utf-8"))
                    action(client, run, "approve_patch", patch_id=quote["patch_id"], quote_id=quote["quote_id"], scope=scope)
                elif command != "show":
                    raise SystemExit(f"unknown command {command}")
            print(json.dumps(summary(client, run), ensure_ascii=False, indent=1, default=str))


if __name__ == "__main__":
    main(sys.argv[1:] or ["ledger"])
