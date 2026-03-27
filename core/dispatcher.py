"""Tiered model dispatch with budget enforcement and escalation policy."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Protocol

from .exceptions import BudgetExceeded
from .execution_types import ExecutionResult
from .executors import ExecutorConfig, build_executor
from .ir import ExecutionPlan, ModelTier
from .telemetry import CostTracker


class SupportsExecute(Protocol):
    async def execute(self, plan: ExecutionPlan, workspace: Path) -> ExecutionResult: ...


@dataclass(frozen=True)
class DispatchAttempt:
    attempt: int
    tier: ModelTier
    model_id: str
    cost_usd: float
    prompt_tokens: int
    completion_tokens: int


class TieredDispatcher:
    """Single authorized caller for LLM backends with budgets and one-step escalation."""

    def __init__(
        self,
        *,
        draft_executor: SupportsExecute | None,
        production_executor: SupportsExecute,
        draft_model: str | None = None,
        production_model: str | None = None,
        cost_tracker: CostTracker | None = None,
    ) -> None:
        self.draft_executor = draft_executor
        self.production_executor = production_executor
        self.draft_model = draft_model or "gpt-4o-mini"
        self.production_model = production_model or "gpt-5"
        self.cost_tracker = cost_tracker or CostTracker()

    @classmethod
    def from_executor_config(cls, config: ExecutorConfig) -> "TieredDispatcher":
        production = build_executor(config)
        draft_model = getattr(config, "draft_model", None) or "gpt-4o-mini"
        production_model = getattr(config, "heavy_model", None) or config.model or "gpt-5"
        draft_config = config.model_copy(update={"model": draft_model})
        return cls(
            draft_executor=build_executor(draft_config),
            production_executor=production,
            draft_model=draft_model,
            production_model=production_model,
        )

    async def execute(self, plan: ExecutionPlan, workspace: Path) -> ExecutionResult:
        attempt_plan = self.plan_for_attempt(plan, attempt=1)
        result = await self._executor_for_tier(attempt_plan.resource_constraints.model_tier).execute(attempt_plan, workspace)
        telemetry = self._cost_for_result(attempt_plan, result)
        result.metadata.update(
            {
                "dispatch_attempt": 1,
                "tier": attempt_plan.resource_constraints.model_tier,
                "cost_usd": telemetry.cost_usd,
                "prompt_tokens": telemetry.prompt_tokens,
                "completion_tokens": telemetry.completion_tokens,
            }
        )
        self._check_budget(attempt_plan, spent_cost=telemetry.cost_usd)
        return result

    def plan_for_attempt(self, plan: ExecutionPlan, *, attempt: int) -> ExecutionPlan:
        if attempt == 1 and plan.resource_constraints.model_tier == ModelTier.DRAFT:
            return plan.model_copy(update={"model_id": self.draft_model})
        return plan.model_copy(
            update={
                "model_id": self.production_model if attempt > 1 or plan.resource_constraints.model_tier == ModelTier.PRODUCTION else self.draft_model,
                "resource_constraints": plan.resource_constraints.model_copy(
                    update={"model_tier": ModelTier.PRODUCTION if attempt > 1 else plan.resource_constraints.model_tier}
                ),
            }
        )

    def next_attempt_plan(self, plan: ExecutionPlan, *, attempt: int, spent_cost: float) -> ExecutionPlan | None:
        if attempt >= plan.resource_constraints.max_attempts:
            return None
        if not plan.resource_constraints.allow_escalation:
            return None
        if plan.resource_constraints.model_tier != ModelTier.DRAFT:
            return None
        escalated = self.plan_for_attempt(plan, attempt=2)
        self._check_budget(escalated, spent_cost=spent_cost)
        return escalated

    def _executor_for_tier(self, tier: ModelTier) -> SupportsExecute:
        if tier == ModelTier.DRAFT and self.draft_executor is not None:
            return self.draft_executor
        return self.production_executor

    def _cost_for_result(self, plan: ExecutionPlan, result: ExecutionResult) -> DispatchAttempt:
        prompt_tokens = int(result.metadata.get("prompt_tokens", 0))
        completion_tokens = int(result.metadata.get("completion_tokens", 0))
        cost_usd = self.cost_tracker.estimate(
            plan.model_id,
            prompt_tokens=prompt_tokens,
            completion_tokens=completion_tokens,
        )
        return DispatchAttempt(
            attempt=int(result.metadata.get("dispatch_attempt", 1)),
            tier=plan.resource_constraints.model_tier,
            model_id=plan.model_id,
            cost_usd=cost_usd,
            prompt_tokens=prompt_tokens,
            completion_tokens=completion_tokens,
        )

    def _check_budget(self, plan: ExecutionPlan, *, spent_cost: float) -> None:
        max_cost = plan.resource_constraints.max_cost_usd
        if max_cost is not None and spent_cost > max_cost:
            raise BudgetExceeded(f"task exceeded cost budget: {spent_cost} > {max_cost}")
