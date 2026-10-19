"""V10c disposable-database verification. Never loads project .env files.

Production connections are impossible: only loopback/nondefault MySQL is allowed.
The SQLite switch tests this harness itself and is not MySQL acceptance evidence.
"""
from __future__ import annotations

import argparse
from concurrent.futures import ThreadPoolExecutor
from contextlib import contextmanager
from copy import deepcopy
from datetime import datetime, timezone
import hashlib
import json
import os
from pathlib import Path
import socket
import sys
import tempfile
from threading import Barrier, Lock, get_ident
import time
import traceback

HEAD, V2_HEAD = "20261019_005", "20261018_002"
DB_PREFIX = "cinecrew_v10c_"
REAL_CALLS = {"http_attempts": 0, "blocked_socket_attempts": 0,
              "llm_provider_calls": 0, "image_provider_calls": 0, "video_provider_calls": 0}


def canonical(value):
    return json.dumps(value, ensure_ascii=False, sort_keys=True, default=str)


def require_temp(path):
    resolved = Path(path).resolve()
    allowed = Path(tempfile.gettempdir()).resolve()
    # A caller may set TEMP explicitly to the stable Windows temporary directory.
    if resolved == allowed or allowed not in resolved.parents:
        raise ValueError("V10c evidence/storage must be a child of the process TEMP directory")
    return resolved


def isolate_environment(work):
    import dotenv
    dotenv.load_dotenv = lambda *a, **kw: False
    import dotenv.main
    dotenv.main.load_dotenv = dotenv.load_dotenv
    def forbidden(*a, **kw):
        raise AssertionError("V10c must never parse dotenv configuration")
    dotenv.dotenv_values = dotenv.main.dotenv_values = forbidden
    os.environ.update({
        "PYTHONDONTWRITEBYTECODE": "1", "PYTHON_DOTENV_DISABLED": "1",
        "DATABASE_URL": "sqlite:///:memory:", "MODEL_ADAPTER_MODE": "mock",
        "DASHSCOPE_API_KEY": "", "DEEPSEEK_API_KEY": "", "OPENAI_API_KEY": "",
        "MQ_ENABLED": "false", "MQ_WORKER_ACTIVE": "false", "REDIS_URL": "",
        "JOB_QUEUE_ENABLED": "false", "API_AUTH_REQUIRED": "false",
        "AUTO_REPAIR_SCHEMA": "false", "AGENT_MODE_ENABLED": "true",
        "AGENT_V3_ENABLED": "true", "AGENT_ACCEPT_NEW_RUNS": "true", "AGENT_ALLOWED_USERS": "",
        "AGENT_SEARCH_PROVIDER": "mock", "AGENT_V3_PLANNING_CREDITS": "20",
        "AGENT_AUTO_APPROVE_CREDITS": "0", "AGENT_MAX_BUDGET": "500",
        "AGENT_V3_DEFAULT_TEXT_MODEL": "deepseek-v4.1-flash",
        "AGENT_V3_DEFAULT_VISION_MODEL": "qwen3.7-plus",
        "DEFAULT_IMAGE_MODEL": "wan2.6-image", "DEFAULT_I2V_MODEL": "wan2.7-i2v",
        "FAILURE_AGENT_ON_ERROR": "false", "FAILURE_AGENT_ENABLED": "false",
        "VIDEO_COMPRESSION_ENABLED": "false", "FIRST_FRAME_IMAGE_ENABLED": "true",
        "I2V_ENABLED": "true", "T2V_ENABLED": "false", "R2V_FLASH_ENABLED": "false",
        "POLL_INTERVAL_SEC": "0", "MAX_POLL_ROUNDS": "3",
        "STORAGE_ROOT": str(work / "bootstrap-storage"),
        "UPLOAD_FOLDER": str(work / "bootstrap-storage" / "uploads"),
        "AGENT_CHECKPOINT_PATH": str(work / "checkpoints.sqlite"),
        **{f"AGENT_{role}_MODEL": "deepseek-v4.1-flash" for role in (
            "PRODUCER", "RESEARCH", "CREATIVE", "DIRECTOR", "PROMPT_SMITH", "CRITIC", "REPAIR", "PLANNER")},
        "AGENT_VISION_MODEL": "qwen3.7-plus",
    })


def install_network_guard(port, sqlite_only):
    import requests
    def blocked_http(*a, **kw):
        REAL_CALLS["http_attempts"] += 1
        raise AssertionError("All provider HTTP is disabled in V10c")
    requests.sessions.Session.send = blocked_http
    original_connect, original_connect_ex = socket.socket.connect, socket.socket.connect_ex
    def check(address):
        if (not sqlite_only and isinstance(address, tuple) and len(address) >= 2
                and address[0] in {"127.0.0.1", "::1"} and address[1] == port):
            return
        REAL_CALLS["blocked_socket_attempts"] += 1
        raise AssertionError("V10c socket outside disposable MySQL endpoint")
    def connect(self, address):
        check(address)
        return original_connect(self, address)
    def connect_ex(self, address):
        check(address)
        return original_connect_ex(self, address)
    socket.socket.connect, socket.socket.connect_ex = connect, connect_ex


def make_app(backend, work, database, args):
    from app import create_app
    if args.sqlite_self_check:
        uri = f"sqlite:///{(work / (database + '.sqlite')).as_posix()}"
        options = {"connect_args": {"timeout": 30}}
    else:
        from sqlalchemy import URL
        uri = URL.create("mysql+pymysql", username="root", password=os.environ["V10C_MYSQL_PASSWORD"],
                         host="127.0.0.1", port=args.port, database=database, query={"charset": "utf8mb4"})
        options = {"pool_pre_ping": True, "pool_size": 5, "max_overflow": 5,
                   "connect_args": {"ssl": {"check_hostname": False}, "connect_timeout": 10,
                                    "read_timeout": 60, "write_timeout": 60}}
    storage = work / database / "storage"
    return create_app("testing", config_overrides={
        "SQLALCHEMY_DATABASE_URI": uri, "SQLALCHEMY_ENGINE_OPTIONS": options,
        "AUTO_REPAIR_SCHEMA": False, "STORAGE_ROOT": str(storage),
        "UPLOAD_FOLDER": str(storage / "uploads"), "MODEL_ADAPTER_MODE": "mock",
        "MQ_ENABLED": False, "JOB_QUEUE_ENABLED": False, "FAILURE_AGENT_ENABLED": False,
        "AGENT_MODE_ENABLED": True, "AGENT_V3_ENABLED": True,
        "AGENT_CHECKPOINT_PATH": str(work / database / "checkpoints.sqlite"),
    })


def cli(app, *args):
    response = app.test_cli_runner().invoke(args=list(args))
    if response.exit_code != 0:
        raise RuntimeError(f"CLI {' '.join(args)} failed: {response.output}; {response.exception!r}")
    return {"command": list(args), "exit_code": response.exit_code, "output": response.output}


def version():
    from app.extensions import db
    from sqlalchemy import text
    return db.session.execute(text("SELECT version_num FROM alembic_version")).scalar_one()


def schema_evidence():
    from app.extensions import db
    from app.models import AgentDelegation, AgentStep, AgentWorkspaceItem, PlanNodeTask
    from sqlalchemy import inspect
    inspector, result = inspect(db.engine), {}
    for model in (AgentDelegation, AgentStep, AgentWorkspaceItem, PlanNodeTask):
        name = model.__tablename__
        columns = {item["name"] for item in inspector.get_columns(name)}
        assert columns == set(model.__table__.columns.keys()), (name, columns)
        actual = {tuple(item["column_names"]) for item in inspector.get_unique_constraints(name)}
        expected = {tuple(column.name for column in constraint.columns)
                    for constraint in model.__table__.constraints
                    if constraint.__class__.__name__ == "UniqueConstraint"}
        assert expected <= actual, (name, actual, expected)
        result[name] = {"columns": sorted(columns), "unique_constraints": sorted(actual),
                        "foreign_keys": inspector.get_foreign_keys(name),
                        "checks": inspector.get_check_constraints(name)}
    return result


def preserved_records(insert=False):
    from app.extensions import db
    from sqlalchemy import MetaData, Table, select
    metadata, now = MetaData(), datetime(2026, 10, 19, 0, 0)
    data = {
        "series": {"series_id": "v10c_legacy", "name": "迁移保留证据", "description": "UTF-8: 猫🐈",
                   "is_default": False, "created_at": now, "updated_at": now},
        "agent_runs": {"run_id": "agent_v10c_legacy", "owner_id": "local", "request_key": "legacy",
                       "request": {"schema_version": 2, "text": "保留历史", "attachment_ids": [], "budget_limit": 100},
                       "status": "success", "snapshot": {"proof": {"unicode": "猫🐈", "nested": [None, 0, False]}},
                       "command": None, "error": None, "resume_count": 0, "created_at": now, "updated_at": now},
        "agent_plan_versions": {"run_id": "agent_v10c_legacy", "version": 1, "author": "system", "parent_version": None,
                                "plan": {"proof": "original v2 plan"}, "story_package": {}, "check": {"issues": []},
                                "created_at": now},
        "tool_invocations": {"invocation_id": "tinv_v10c_legacy", "tool_name": "legacy_probe", "idempotency_key": "legacy_key",
                             "caller_role": "production", "budget_scope": "agent_v10c_legacy", "status": "success",
                             "attempt": 1, "input_payload": {"proof": ["原文", None]}, "output_payload": {"ok": True},
                             "job_id": None, "estimated_cost": 1.25, "duration_ms": 10,
                             "created_at": now, "updated_at": now},
    }
    result = {}
    for name, values in data.items():
        table = Table(name, metadata, autoload_with=db.engine)
        if insert:
            db.session.execute(table.insert().values(**values))
            db.session.commit()
        # Select exactly the v2 columns: v3-added nullable fields are checked separately.
        row = db.session.execute(select(*(table.c[key] for key in values))).mappings().one()
        result[name] = dict(row)
    return result


def scripted(app, *, barrier=None):
    from app.tools.scripted_llm import ScriptedLLM
    def call(name, arguments):
        return {"id": name + str(len(arguments)), "name": name, "arguments": arguments}
    plan = {"title": "V10c Mock 猫咪", "goal": "生成猫咪图片并人工审核交付", "nodes": [{
        "id": "image", "tool": "generate_image", "inputs": {"prompt": "A happy orange cat"},
        "model_id": "wan2.6-image", "params": {"n": 1}, "gate": None,
        "origin": {"agent": "producer", "skills": []}, "rationale": "Single image smoke"}],
        "deliverables": [{"kind": "image", "node_id": "image", "output": "image"}]}
    responses = {"producer": [
        [call("write_workspace", {"key": "brief", "kind": "brief", "payload": {
            "deliverable": "image", "summary": "生成一张猫的图片", "confidence": 0.99}})],
        [call("write_workspace", {"key": "plan", "kind": "plan_draft", "payload": plan})],
        [call("submit_plan", {"plan_ref": {"key": "plan", "version": 1}})],
    ]}
    class ObservedLLM(ScriptedLLM):
        def __init__(self):
            super().__init__(responses)
            self.overlap = []
            self.lock = Lock()
        def complete(self, agent, step, **kwargs):
            if barrier is not None and agent == "producer" and step == 0:
                entry = {"thread_id": get_ident(), "entered": time.perf_counter()}
                with self.lock:
                    self.overlap.append(entry)
                barrier.wait(timeout=30)
                entry["released"] = time.perf_counter()
            return super().complete(agent, step, **kwargs)
    llm = ObservedLLM()
    app.extensions["agent_v3_scripted_llm"] = llm
    return llm


def plan_one(app, identity):
    from app.agents import runtime
    from app.extensions import db
    from app.models import AgentRun, AgentDelegation, AgentPlanVersion, AgentWorkspaceItem, AgentStep, ToolInvocation
    from langgraph.checkpoint.memory import InMemorySaver
    with app.app_context():
        client = app.test_client()
        response = client.post("/api/agent/runs", json={"text": "生成一张猫的图片", "request_key": identity,
                                                       "attachment_ids": [], "budget_limit": 100})
        assert response.status_code == 202, response.json
        run_id = response.json["data"]["run_id"]
        run = AgentRun.query.filter_by(run_id=run_id).one()
        states, saver = [run.status], InMemorySaver()
        for _ in range(8):
            runtime.advance(run, saver=saver)
            states.append(run.status)
            if run.status == "awaiting_plan_review":
                break
            assert run.status not in {"attention", "failed", "cancelled", "success"}, (run.status, run.error)
        assert run.status == "awaiting_plan_review", (states, run.error)
        delegations = AgentDelegation.query.filter_by(run_id=run_id).all()
        assert len(delegations) == 1 and delegations[0].llm_calls == 3
        versions = AgentPlanVersion.query.filter_by(run_id=run_id).all()
        assert len(versions) == 1 and versions[0].version == 1 and not versions[0].check["issues"]
        workspace = AgentWorkspaceItem.query.filter_by(run_id=run_id).all()
        assert {(row.key, row.version) for row in workspace} == {("brief", 1), ("plan", 1)}
        ledger = ToolInvocation.query.filter_by(budget_scope=run_id).all()
        assert all(row.status == "success" for row in ledger)
        assert len({row.idempotency_key for row in ledger}) == len(ledger)
        result = {"run_id": run_id, "states": states, "delegation_ids": [row.id for row in delegations],
                  "workspace_ids": [row.id for row in workspace], "plan_ids": [row.id for row in versions],
                  "ledger_ids": [row.invocation_id for row in ledger], "llm_rounds": 3,
                  "credits": sum(row.estimated_cost for row in ledger),
                  "step_count": AgentStep.query.filter_by(run_id=run_id).count()}
        db.session.remove()
        return result


def smoke(app):
    from app.agent.worker import AgentWorker
    from app.extensions import db
    from app.models import AgentRun, PlanNodeTask, ToolInvocation
    from app.services.job_run_service import JobRunService
    from langgraph.checkpoint.memory import InMemorySaver
    scripted(app)
    result = plan_one(app, "v10c-smoke")
    with app.app_context():
        client, worker = app.test_client(), AgentWorker(None, None, v3_saver=InMemorySaver())
        run_id = result["run_id"]
        original = JobRunService.__dict__["start"]
        JobRunService.start = JobRunService.run_inline
        try:
            for action, expected in (("approve_plan", "awaiting_result_review"), ("approve_results", "success")):
                response = client.post(f"/api/agent/runs/{run_id}/actions", json={
                    "action": action, "request_key": "v10c_" + action, "plan_version": 1})
                assert response.status_code == 202, response.json
                for _ in range(8):
                    worker.advance(run_id)
                    db.session.remove()
                    run = AgentRun.query.filter_by(run_id=run_id).one()
                    result["states"].append(run.status)
                    if run.status == expected:
                        break
                    assert run.status not in {"attention", "failed"}, (run.status, run.error)
                assert run.status == expected, (run.status, run.error)
            tasks = PlanNodeTask.query.filter_by(run_id=run_id).all()
            assert len(tasks) == 1 and tasks[0].status == "success" and tasks[0].artifact_ids
            rows = ToolInvocation.query.filter_by(budget_scope=run_id).all()
            assert sum(row.tool_name == "generate_image" for row in rows) == 1
            result.update(mock_media_jobs=1, task_ids=[row.id for row in tasks],
                          ledger=[{"tool": row.tool_name, "status": row.status, "cost": row.estimated_cost} for row in rows],
                          credits=sum(row.estimated_cost for row in rows))
        finally:
            JobRunService.start = original
            db.session.remove()
    return result


def concurrent_planning(app):
    llm = scripted(app, barrier=Barrier(2))
    with ThreadPoolExecutor(max_workers=2) as pool:
        futures = [pool.submit(plan_one, app, f"v10c-concurrent-{i}") for i in range(2)]
        runs = [future.result(timeout=120) for future in futures]
    assert len(llm.overlap) == 2
    assert len({entry["thread_id"] for entry in llm.overlap}) == 2
    assert max(entry["entered"] for entry in llm.overlap) <= min(entry["released"] for entry in llm.overlap)
    for key in ("delegation_ids", "workspace_ids", "plan_ids", "ledger_ids"):
        assert not set(runs[0][key]) & set(runs[1][key]), key
    assert len(llm.calls) == 6 and all(run["llm_rounds"] == 3 for run in runs)
    return {"runs": runs, "overlap": llm.overlap, "mock_llm_calls": len(llm.calls)}


def run(args):
    work, backend = require_temp(args.work), Path(args.backend).resolve()
    work.mkdir(parents=True, exist_ok=True)
    assert not (work / "mysql-evidence.json").exists(), "Use a fresh evidence directory"
    isolate_environment(work)
    install_network_guard(args.port, args.sqlite_self_check)
    sys.path.insert(0, str(backend))
    os.chdir(backend)
    from app.extensions import db
    from sqlalchemy import inspect, text
    evidence = {"kind": "sqlite_harness_self_check" if args.sqlite_self_check else "mysql_v10c",
                "started_at": datetime.now(timezone.utc).isoformat(), "head": HEAD, "v2_head": V2_HEAD,
                "endpoint": None if args.sqlite_self_check else f"127.0.0.1:{args.port}",
                "checks": [], "real_calls": REAL_CALLS, "success": False}
    apps = []
    def check(name, callback):
        started = time.perf_counter()
        try:
            detail = callback()
            evidence["checks"].append({"name": name, "passed": True, "seconds": time.perf_counter() - started, "detail": detail})
            print(json.dumps({"check": name, "passed": True}, ensure_ascii=False), flush=True)
            return True
        except Exception as error:
            evidence["checks"].append({"name": name, "passed": False, "seconds": time.perf_counter() - started,
                                       "root_cause": f"{type(error).__name__}: {error}", "traceback": traceback.format_exc()})
            print(json.dumps({"check": name, "passed": False, "error": str(error)}, ensure_ascii=False), flush=True)
            return False
    try:
        databases = [DB_PREFIX + "fresh", DB_PREFIX + "upgrade"]
        if not args.sqlite_self_check:
            import pymysql
            with pymysql.connect(host="127.0.0.1", port=args.port, user="root",
                                 password=os.environ["V10C_MYSQL_PASSWORD"], charset="utf8mb4",
                                 ssl={"check_hostname": False}, autocommit=True) as connection:
                with connection.cursor() as cursor:
                    cursor.execute("SELECT VERSION()")
                    evidence["mysql_version"] = cursor.fetchone()[0]
                    assert evidence["mysql_version"].startswith("8.")
                    cursor.execute("SHOW STATUS LIKE 'Ssl_cipher'")
                    evidence["tls_cipher"] = cursor.fetchone()[1]
                    assert evidence["tls_cipher"], "Disposable MySQL connection must use TLS"
                    for name in databases:
                        cursor.execute("CREATE DATABASE `" + name + "` CHARACTER SET utf8mb4")
        fresh, legacy = [make_app(backend, work, name, args) for name in databases]
        apps.extend([fresh, legacy])
        def migrate_fresh():
            with fresh.app_context():
                assert not inspect(db.engine).get_table_names()
                output = cli(fresh, "db", "upgrade", "head")
                assert version() == HEAD
                schema = schema_evidence()
                db.session.remove()
                return {"cli": output, "schema": schema}
        fresh_ok = check("fresh_upgrade_head", migrate_fresh)
        def migrate_legacy():
            with legacy.app_context():
                assert not inspect(db.engine).get_table_names()
                first = cli(legacy, "db", "upgrade", V2_HEAD)
                assert version() == V2_HEAD
                assert not inspect(db.engine).has_table("agent_delegations")
                before = preserved_records(insert=True)
                db.session.remove()
                second = cli(legacy, "db", "upgrade", "head")
                assert version() == HEAD
                after = preserved_records()
                assert canonical(before) == canonical(after), "Legacy values changed during upgrade"
                added = db.session.execute(text("SELECT caller_agent,delegation_id FROM tool_invocations")).one()
                assert tuple(added) == (None, None)
                schema = schema_evidence()
                db.session.remove()
                return {"cli": [first, second], "preserved_tables": sorted(before), "record_count": len(before),
                        "preserved_sha256": hashlib.sha256(canonical(before).encode()).hexdigest(), "schema": schema}
        check("v2_head_upgrade_preserves_history", migrate_legacy)
        if fresh_ok:
            with fresh.app_context():
                seed = cli(fresh, "seed-defaults")
                evidence["seed"] = seed
            check("v3_mock_smoke", lambda: smoke(fresh))
            check("two_runs_concurrent_planning", lambda: concurrent_planning(fresh))
        assert not any(REAL_CALLS.values()), REAL_CALLS
        evidence["success"] = len(evidence["checks"]) == 4 and all(item["passed"] for item in evidence["checks"])
    except Exception as error:
        evidence["fatal"] = {"root_cause": f"{type(error).__name__}: {error}", "traceback": traceback.format_exc()}
    finally:
        for app in apps:
            with app.app_context():
                db.session.remove()
                db.engine.dispose()
        evidence["finished_at"] = datetime.now(timezone.utc).isoformat()
        (work / "mysql-evidence.json").write_text(json.dumps(evidence, ensure_ascii=False, indent=2, default=str), encoding="utf-8")
        print(json.dumps({"success": evidence["success"], "evidence": str(work / "mysql-evidence.json"), "real_calls": REAL_CALLS}, ensure_ascii=False), flush=True)
    return 0 if evidence["success"] else 1


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--backend", type=Path, required=True)
    parser.add_argument("--work", type=Path, required=True)
    parser.add_argument("--port", type=int, default=3307)
    parser.add_argument("--sqlite-self-check", action="store_true")
    args = parser.parse_args()
    if not 1024 <= args.port <= 65535 or args.port == 3306:
        parser.error("Only a nondefault high MySQL port is allowed")
    if not args.sqlite_self_check and not os.environ.get("V10C_MYSQL_PASSWORD"):
        parser.error("V10C_MYSQL_PASSWORD must contain the disposable container password")
    return run(args)


if __name__ == "__main__":
    raise SystemExit(main())
