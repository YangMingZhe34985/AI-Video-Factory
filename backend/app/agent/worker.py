"""Single-host durable worker, separate from Gunicorn and request lifetimes."""

import sqlite3
import time
from contextlib import contextmanager
from pathlib import Path

import click
from flask import current_app
from langgraph.checkpoint.sqlite import SqliteSaver
from langgraph.types import Command

from app.agent.graph import build_graph
from app.api import AppError
from app.extensions import db
from app.models import AgentRun
from app.skills.budget import BudgetGuard


def checkpoint_path():
    configured = current_app.config.get("AGENT_CHECKPOINT_PATH")
    path = Path(configured) if configured else Path(current_app.config["STORAGE_ROOT"]) / "agent" / "checkpoints.sqlite"
    path.parent.mkdir(parents=True, exist_ok=True)
    return path


@contextmanager
def worker_lock():
    # A separate SQLite transaction is an OS-backed process lock. It is
    # released even on process death and works on both Windows and Linux.
    connection = sqlite3.connect(str(checkpoint_path()) + ".worker-lock", timeout=0)
    try:
        try:
            connection.execute("BEGIN IMMEDIATE")
        except sqlite3.OperationalError as error:
            raise click.ClickException("An Agent worker already owns this checkpoint directory") from error
        yield
    finally:
        connection.close()


class AgentWorker:
    """Call only while holding worker_lock (tests use the same lock)."""

    def __init__(self, graph, graph_v2=None):
        self.graph = graph
        self.graph_v2 = graph_v2

    def tick(self):
        db.session.expire_all()
        ids = [row.run_id for row in AgentRun.query.filter(
            (AgentRun.status.in_(["queued", "understanding", "analyzing", "researching", "planning", "previewing", "producing", "delivering", "editing"])) | AgentRun.command.is_not(None)
        ).order_by(AgentRun.id).all()]
        for run_id in ids:
            self.advance(run_id)

    def advance(self, run_id):
        row = AgentRun.query.filter_by(run_id=run_id).one()
        config = {"configurable": {"thread_id": run_id}, "recursion_limit": 100}
        command = row.command
        version = row.request.get("schema_version", 1)
        graph = {1: self.graph, 2: self.graph_v2}.get(version)
        try:
            if graph is None:
                raise AppError("AGENT_GRAPH_UNAVAILABLE", f"No execution graph for schema version {version}", 500)
            snapshot = graph.get_state(config)
            if not snapshot.values:
                request = row.request
                row.status = "understanding" if version == 2 else "planning"
                db.session.commit()
                value = {"run_id": run_id, "budget_limit": request["budget_limit"], "status": row.status,
                         "shots": {}, "packages": [],
                         "mock": current_app.config.get("MODEL_ADAPTER_MODE") == "mock"}
                if version == 2:
                    value["results"] = []
                else:
                    value.update(goal=request["goal"], shot_count=request["shot_count"],
                                 mode=request.get("mode", "from_scratch"))
            elif snapshot.interrupts:
                kind = snapshot.interrupts[0].value["kind"]
                if command and command.get("command_id") and command["command_id"] == snapshot.values.get("last_command_id"):
                    # A revision can return to the same delivery interrupt before
                    # the inbox is cleared. Its checkpoint receipt prevents rebilling.
                    self._save(row, snapshot.values, None)
                    return
                if kind in {"tasks", "analysis", "previews", "production_tasks", "delivery_tasks"}:
                    value = Command(resume={"action": "poll"})
                elif command and command["action"] in {"approval": {"approve", "reject"}, "delivery": {"deliver", "revise"},
                                                       "clarify": {"answer"},
                                                       "delivery_review": {"retry_delivery"},
                                                       "production_review": {"retry_shot", "redo_shot", "review_plan", "approve_videos"},
                                                       "characters": {"approve_characters", "regenerate", "reject"},
                                                       "storyboard": {"edit_plan", "regenerate", "regenerate_stale", "approve_storyboard", "reject"}}.get(kind, set()):
                    value = Command(resume=command)
                else:
                    self._save(row, snapshot.values, None)
                    return
            else:
                # Continue the latest checkpoint after a crash. In particular,
                # never replay an approval against a later interrupt.
                if (version == 2 and command and command.get("action") == "start_production"
                        and snapshot.values.get("status") == "storyboard_approved"):
                    # Resume the successor of the completed C approval without
                    # replaying creative/preview work or altering historical runs.
                    graph.update_state(config, {"production_command": command}, as_node="story_v2_apply")
                if (version == 2 and command and command.get("action") in {"start_delivery", "retry_delivery"}
                        and snapshot.values.get("status") in {"videos_approved", "success"}):
                    graph.update_state(config, {"delivery_command": command, "status": "editing"}, as_node="production_v2_tick")
                value = None
            # Clear inbox only AFTER graph/checkpoint succeeds. If killed here,
            # the persisted checkpoint determines whether to consume it again.
            graph.invoke(value, config)
            result = graph.get_state(config)
            self._save(row, result.values, None)
        except Exception as error:
            db.session.rollback()
            current_app.logger.exception("Agent run failed: %s", run_id)
            row = AgentRun.query.filter_by(run_id=run_id).one()
            latest = graph.get_state(config) if graph is not None else None
            row.snapshot = self._merged_snapshot(row, (latest.values if latest else None) or row.snapshot or {})
            row.status = "needs_attention"
            row.error = {"code": getattr(error, "code", "AGENT_FAILED"), "message": str(error)}
            row.command = None
            db.session.commit()

    @staticmethod
    def _merged_snapshot(row, values):
        # These receipts commit with relational plan/task writes, independently
        # of graph checkpoints; never drop them on a crash or an inbox retry.
        preserved = {key: row.snapshot[key] for key in ("plan_operations", "story_action_receipts", "story_model_overrides",
                     "production", "production_action_receipts", "transform", "production_repairs",
                     "delivery", "delivery_action_receipts")
                     if key in (row.snapshot or {})}
        return {**dict(values), **preserved}

    @staticmethod
    def _save(row, values, error):
        # Refresh after graph tool calls on other sessions.
        db.session.refresh(row)
        previous_status = row.status
        row.snapshot = AgentWorker._merged_snapshot(row, values)
        row.status = values.get("status", "needs_attention")
        row.error = error or values.get("delivery_error") or values.get("production_error") or values.get("transform_error")
        row.command = None
        db.session.commit()
        if previous_status != row.status:
            current_app.logger.info("agent_transition run_id=%s from=%s to=%s estimated_credits=%s",
                                    row.run_id, previous_status, row.status, BudgetGuard.spent(row.run_id))


def run_worker(once=False):
    from app.agent.graph_v2 import build_graph as build_graph_v2
    if not current_app.config.get("AGENT_MODE_ENABLED"):
        raise click.ClickException("AGENT_MODE_ENABLED must be true")
    # This is a dedicated process. Paid retries must not bypass the Agent's
    # tool ledger/approved budget via the classic failure-decision hook.
    current_app.config["FAILURE_AGENT_ENABLED"] = False
    current_app.config["AGENT_WORKER_ACTIVE"] = True
    with worker_lock(), SqliteSaver.from_conn_string(str(checkpoint_path())) as saver:
        worker = AgentWorker(build_graph(saver), build_graph_v2(saver))
        while True:
            worker.tick()
            db.session.remove()
            if once:
                return
            time.sleep(max(0.1, float(current_app.config.get("AGENT_POLL_INTERVAL_SEC", 3))))
