"""Static cost estimates and per-scope budget enforcement.

Costs are abstract credits used to stop runaway or duplicated generation;
they are estimates, not provider billing. Submission is treated as billable
even if the provider task later fails, so the estimate errs high.
"""

from flask import current_app
from sqlalchemy import func

from app.api import AppError
from app.extensions import db
from app.models import ToolInvocation

LLM_CALL = 1.0
IMAGE_GENERATION = 2.0
VIDEO_GENERATION = 10.0

NODE_COSTS = {
    "reverse_prompts": LLM_CALL,
    "rewrite_prompts": LLM_CALL,
    "reverse_prompts4r2v": LLM_CALL,
    "rewrite_t2i_to_i2i": LLM_CALL,
    "failure_agent": LLM_CALL,
    "submit_first_frame_image": IMAGE_GENERATION,
    "submit_t2v": VIDEO_GENERATION,
    "submit_i2v": VIDEO_GENERATION,
    "submit_r2v_flash": VIDEO_GENERATION,
}
# I2I test nodes submit one task per sample.
PER_SAMPLE_NODE_COSTS = {
    "submit_i2i_test_image": IMAGE_GENERATION,
    "submit_i2i_test_i2v": VIDEO_GENERATION,
}


def estimate_nodes_cost(node_keys, sample_count: int = 1) -> float:
    total = 0.0
    for key in node_keys:
        total += NODE_COSTS.get(key, 0.0)
        total += PER_SAMPLE_NODE_COSTS.get(key, 0.0) * max(sample_count, 1)
    return total


class BudgetGuard:
    @staticmethod
    def limit_for(budget_limit: float | None) -> float:
        if budget_limit is not None:
            return float(budget_limit)
        return float(current_app.config.get("SKILL_DEFAULT_BUDGET", 100))

    @staticmethod
    def spent(budget_scope: str) -> float:
        value = (
            db.session.query(func.coalesce(func.sum(ToolInvocation.estimated_cost), 0.0))
            .filter(
                ToolInvocation.budget_scope == budget_scope,
                ToolInvocation.status != "rejected",
            )
            .scalar()
        )
        return float(value or 0.0)

    @classmethod
    def check(cls, budget_scope: str, budget_limit: float | None, cost: float) -> None:
        if cost <= 0:
            return
        limit = cls.limit_for(budget_limit)
        spent = cls.spent(budget_scope)
        if spent + cost > limit:
            raise AppError(
                "BUDGET_EXCEEDED",
                f"Budget exceeded for scope '{budget_scope}': "
                f"spent {spent:g} + requested {cost:g} > limit {limit:g}",
                402,
                payload={
                    "budget_scope": budget_scope,
                    "spent": spent,
                    "requested": cost,
                    "limit": limit,
                },
            )
