from __future__ import annotations

import json
from types import SimpleNamespace
from typing import Any

from flask import current_app

from app.api import AppError
from app.extensions import db
from app.models import Job, JobNodeRun, WorkflowNode
from app.services.event_service import EventService
from app.services.node_runner import NodeRunner


class FailureDecisionService:
    """Lightweight decision hook used after a workflow node fails."""

    NON_RETRYABLE_CODES = {
        "DEPENDENCY_MISSING",
        "PROMPT_NOT_FOUND",
        "MODEL_NOT_FOUND",
        "NODE_DISABLED",
        "NODE_NOT_FOUND",
        "INVALID_INPUT",
        "MISSING_INPUT",
    }
    ACTIONS = {"retry_node", "skip_node", "fail_path", "fail_job"}
    ACTION_ALIASES = {
        "RETRY_NODE": "retry_node",
        "SKIP_NODE": "skip_node",
        "FAIL_PATH": "fail_path",
        "TERMINATE_PATH": "fail_path",
        "FAIL_JOB": "fail_job",
        "CANCEL_JOB": "fail_job",
        "PAUSE_JOB": "fail_job",
        "NEED_HUMAN": "fail_path",
        "CONTINUE_FROM_NODE": "skip_node",
    }

    @classmethod
    def decide(
        cls,
        *,
        job: Job,
        failed_run: JobNodeRun,
        error_detail: dict[str, Any] | None,
        retries_used: int = 0,
    ) -> dict[str, Any]:
        max_retries = cls.max_retries()
        code = (error_detail or {}).get("code") or "INTERNAL_ERROR"
        if code in cls.NON_RETRYABLE_CODES:
            decision = cls._default_decision(
                "fail_path",
                f"{code} is not retryable.",
                max_retries=max_retries,
                retries_used=retries_used,
                source="policy",
            )
            cls.record_decision(job, failed_run, decision)
            return decision

        if not current_app.config.get("FAILURE_AGENT_ENABLED", True):
            decision = cls._default_decision(
                "fail_path",
                "Failure agent is disabled; failing only the affected path.",
                max_retries=max_retries,
                retries_used=retries_used,
                source="disabled",
            )
            cls.record_decision(job, failed_run, decision)
            return decision

        try:
            decision = cls._llm_decision(
                job=job,
                failed_run=failed_run,
                error_detail=error_detail or {},
                max_retries=max_retries,
                retries_used=retries_used,
            )
        except Exception as error:
            current_app.logger.exception("Failure agent decision failed: %s", error)
            decision = cls._default_decision(
                "fail_path",
                f"Failure agent failed; using conservative path failure. {error}",
                max_retries=max_retries,
                retries_used=retries_used,
                source="fallback",
            )
            EventService.record(
                job,
                "FAILURE_AGENT_FAILED",
                message="Failure agent failed; fallback decision used",
                node_key=failed_run.node_key,
                payload={"error": str(error), "decision": decision},
                level="warning",
            )

        decision = cls._normalize_decision(
            decision,
            max_retries=max_retries,
            retries_used=retries_used,
            error_code=code,
        )
        cls.record_decision(job, failed_run, decision)
        return decision

    @staticmethod
    def max_retries() -> int:
        configured = int(current_app.config.get("FAILURE_AGENT_MAX_RETRIES", 1))
        return min(2, max(0, configured))

    @classmethod
    def record_decision(
        cls,
        job: Job,
        failed_run: JobNodeRun,
        decision: dict[str, Any],
    ) -> None:
        snapshot = failed_run.output_snapshot if isinstance(failed_run.output_snapshot, dict) else {}
        snapshot = dict(snapshot)
        snapshot["failure_agent_decision"] = decision
        failed_run.output_snapshot = snapshot
        EventService.record(
            job,
            "FAILURE_AGENT_DECISION",
            message=f"Failure agent decision: {decision.get('action')}",
            node_key=failed_run.node_key,
            payload=decision,
            level="warning" if decision.get("action") != "fail_job" else "error",
        )
        db.session.commit()

    @classmethod
    def _llm_decision(
        cls,
        *,
        job: Job,
        failed_run: JobNodeRun,
        error_detail: dict[str, Any],
        max_retries: int,
        retries_used: int,
    ) -> dict[str, Any]:
        runner = NodeRunner()
        failure_node = (
            WorkflowNode.query.filter_by(template_id=None, node_key="failure_agent").first()
            or SimpleNamespace(node_key="failure_agent", config={})
        )
        system_prompt = runner._prompt(job, "failure_agent_system", required=False)
        user_prompt = runner._prompt(job, "failure_agent_user", required=False)
        context = {
            "job": job.to_dict(),
            "failed_run": failed_run.to_dict(),
            "error_detail": error_detail,
            "retry_policy": {
                "max_retries": max_retries,
                "retries_used": retries_used,
                "remaining_retries": max(0, max_retries - retries_used),
                "non_retryable_codes": sorted(cls.NON_RETRYABLE_CODES),
            },
            "allowed_actions": sorted(cls.ACTIONS),
            "instructions": (
                "Return a conservative JSON decision. Prefer fail_path for deterministic "
                "configuration or dependency errors. Retry only likely transient provider, "
                "network, or internal execution failures."
            ),
        }
        rendered_user_prompt = runner._render_prompt_template(
            user_prompt.content if user_prompt else "{{context_json}}",
            context_json=json.dumps(context, ensure_ascii=False, indent=2),
        )
        schema = {
            "type": "object",
            "properties": {
                "action": {
                    "type": "string",
                    "enum": ["retry_node", "skip_node", "fail_path", "fail_job"],
                },
                "reason": {"type": "string"},
                "retry_count": {"type": "integer"},
                "continue_unaffected_paths": {"type": "boolean"},
            },
            "required": ["action", "reason", "retry_count", "continue_unaffected_paths"],
            "additionalProperties": False,
        }
        model = runner._model_for(job, failure_node, "failure_agent", "DEFAULT_PROMPT_REWRITE_MODEL")
        adapter, payload, response = runner._adapter_payload(
            model,
            {
                "task": "failure_decision",
                "system_prompt": system_prompt.content if system_prompt else "",
                "user_prompt": rendered_user_prompt,
                "schema_name": "failure_decision",
                "response_schema": schema,
            },
            params={"temperature": 0.0},
            job=job,
            node=failure_node,
            param_key="failure_agent",
        )
        data = response.get("json") or {}
        data.update(
            {
                "source": "llm",
                "model_id": model.model_id,
                "adapter": adapter.__class__.__name__,
                "raw_response": response,
                "request_payload": payload,
            }
        )
        return data

    @classmethod
    def _normalize_decision(
        cls,
        decision: dict[str, Any],
        *,
        max_retries: int,
        retries_used: int,
        error_code: str,
    ) -> dict[str, Any]:
        raw_action = str(decision.get("action") or "fail_path").strip()
        action = cls.ACTION_ALIASES.get(raw_action, raw_action.lower())
        if action not in cls.ACTIONS:
            action = "fail_path"
        remaining = max(0, max_retries - retries_used)
        retry_count = cls._safe_int(decision.get("retry_count"), default=1 if action == "retry_node" else 0)
        retry_count = min(remaining, max(0, retry_count))
        if action == "retry_node" and (retry_count <= 0 or error_code in cls.NON_RETRYABLE_CODES):
            action = "fail_path"
            retry_count = 0
        return {
            "action": action,
            "reason": str(decision.get("reason") or "No reason provided").strip(),
            "retry_count": retry_count,
            "continue_unaffected_paths": bool(decision.get("continue_unaffected_paths", True)),
            "source": decision.get("source") or "policy",
            "model_id": decision.get("model_id"),
            "adapter": decision.get("adapter"),
        }

    @classmethod
    def _default_decision(
        cls,
        action: str,
        reason: str,
        *,
        max_retries: int,
        retries_used: int,
        source: str,
    ) -> dict[str, Any]:
        return cls._normalize_decision(
            {
                "action": action,
                "reason": reason,
                "retry_count": 0,
                "continue_unaffected_paths": True,
                "source": source,
            },
            max_retries=max_retries,
            retries_used=retries_used,
            error_code="",
        )

    @staticmethod
    def _safe_int(value, default: int = 0) -> int:
        try:
            return int(value)
        except (TypeError, ValueError):
            return default
