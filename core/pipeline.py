"""Async compiler pipeline with passes, cache replay, verification, and compensation."""

from __future__ import annotations

import asyncio
import subprocess
from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from pydantic import BaseModel, ConfigDict, Field

from .action_cache import ActionCache
from .events import EventStore
from .execution_types import ExecutionResult
from .executors import ExecutorConfig
from .exceptions import PipelineFailure
from .ir import ExecutionPlan, FrontendIR, MiddleEndIR, ResourceLimits, SandboxType, VerificationContract
from .saga import Saga
from .verifier import VerificationRunner
from .watcher import AuthorizedWriteWatcher
from .worktree import WorktreeManager


class ExecutorProtocol:
    async def execute(self, plan: ExecutionPlan, workspace: Path) -> ExecutionResult: ...


class PipelineRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    task_id: str
    base_commit: str
    authorized_files: list[str]
    constitution: str
    verification_contracts: list[VerificationContract]
    model_id: str
    repo_root: str
    executor: ExecutorConfig | None = None
    sandbox_type: SandboxType = SandboxType.WORKTREE
    resource_limits: ResourceLimits = Field(
        default_factory=lambda: ResourceLimits(max_runtime_seconds=900, max_memory_mb=2048, max_cpu_count=2)
    )


@dataclass(frozen=True)
class PipelineRunResult:
    frontend_ir: FrontendIR
    middle_end_ir: MiddleEndIR
    execution_plan: ExecutionPlan
    cache_key: str
    cache_hit: bool
    workspace: str
    touched_files: list[str]
    verification: dict[str, Any]
    events: list[dict[str, Any]]


class PassManager:
    """Runs named async passes sequentially while preserving explicit order."""

    def __init__(self) -> None:
        self._passes: list[tuple[str, Callable[[dict[str, Any]], Awaitable[dict[str, Any]]]]] = []

    def add(self, name: str, callback: Callable[[dict[str, Any]], Awaitable[dict[str, Any]]]) -> None:
        self._passes.append((name, callback))

    async def run(self, context: dict[str, Any]) -> dict[str, Any]:
        state = context
        for name, callback in self._passes:
            state["current_pass"] = name
            state = await callback(state)
        return state


class Pipeline:
    """Coordinates lowering, caching, verification, and isolated execution."""

    def __init__(
        self,
        *,
        executor: ExecutorProtocol,
        action_cache: ActionCache,
        verifier: VerificationRunner,
        event_store: EventStore,
        worktree_manager: WorktreeManager | None = None,
    ) -> None:
        self.executor = executor
        self.action_cache = action_cache
        self.verifier = verifier
        self.event_store = event_store
        self.worktree_manager = worktree_manager

    async def run(self, request: PipelineRequest) -> PipelineRunResult:
        manager = PassManager()
        manager.add("frontend", self._pass_frontend)
        manager.add("middle_end", self._pass_middle_end)
        manager.add("execution_plan", self._pass_execution_plan)
        manager.add("execute_or_replay", self._pass_execute_or_replay)

        state = await manager.run({"request": request})
        return PipelineRunResult(
            frontend_ir=state["frontend_ir"],
            middle_end_ir=state["middle_end_ir"],
            execution_plan=state["execution_plan"],
            cache_key=state["cache_key"],
            cache_hit=state["cache_hit"],
            workspace=str(state["workspace"]),
            touched_files=state["touched_files"],
            verification=state["verification"],
            events=state["events"],
        )

    async def _pass_frontend(self, state: dict[str, Any]) -> dict[str, Any]:
        request: PipelineRequest = state["request"]
        frontend_ir = FrontendIR(
            task_id=request.task_id,
            base_commit=request.base_commit,
            authorized_files=request.authorized_files,
        )
        event = self.event_store.append("frontend_lowered", frontend_ir.model_dump(mode="json"))
        return {**state, "frontend_ir": frontend_ir, "events": [event]}

    async def _pass_middle_end(self, state: dict[str, Any]) -> dict[str, Any]:
        request: PipelineRequest = state["request"]
        frontend_ir: FrontendIR = state["frontend_ir"]
        middle = MiddleEndIR(
            **frontend_ir.model_dump(mode="json"),
            constitution=request.constitution,
            verification_contracts=request.verification_contracts,
        )
        event = self.event_store.append(
            "middle_end_lowered",
            {"task_id": middle.task_id, "verification_contracts": middle.model_dump(mode="json")["verification_contracts"]},
        )
        return {**state, "middle_end_ir": middle, "events": [*state["events"], event]}

    async def _pass_execution_plan(self, state: dict[str, Any]) -> dict[str, Any]:
        request: PipelineRequest = state["request"]
        middle: MiddleEndIR = state["middle_end_ir"]
        plan = ExecutionPlan(
            **middle.model_dump(mode="json"),
            model_id=request.model_id,
            sandbox_type=request.sandbox_type,
            resource_limits=request.resource_limits,
        )
        event = self.event_store.append(
            "execution_plan_lowered",
            {"task_id": plan.task_id, "sandbox_type": plan.sandbox_type, "model_id": plan.model_id},
        )
        return {**state, "execution_plan": plan, "events": [*state["events"], event]}

    async def _pass_execute_or_replay(self, state: dict[str, Any]) -> dict[str, Any]:
        request: PipelineRequest = state["request"]
        frontend_ir: FrontendIR = state["frontend_ir"]
        middle: MiddleEndIR = state["middle_end_ir"]
        plan: ExecutionPlan = state["execution_plan"]
        repo_root = Path(request.repo_root).resolve()
        cache_key = self.action_cache.compute_action_key(frontend_ir, middle.constitution)
        watcher = AuthorizedWriteWatcher(repo_root, plan.authorized_files)
        events = list(state["events"])

        cached = self.action_cache.get(cache_key)
        if cached is not None:
            touched_files = self._extract_patch_paths(cached.patch)
            watcher.validate_paths(touched_files)
            self._apply_patch(repo_root, cached.patch)
            event = self.event_store.append("cache_hit", {"cache_key": cache_key, "touched_files": touched_files})
            events.append(event)
            return {
                **state,
                "cache_key": cache_key,
                "cache_hit": True,
                "workspace": repo_root,
                "touched_files": touched_files,
                "verification": cached.verification_summary,
                "events": events,
            }

        pre_patch = self.verifier.run_pre_patch(middle, repo_root)
        events.append(self.event_store.append("verification_pre_patch", {"count": len(pre_patch), "cache_key": cache_key}))

        workspace = repo_root
        saga = Saga()
        try:
            if plan.sandbox_type == SandboxType.WORKTREE:
                if self.worktree_manager is None:
                    self.worktree_manager = WorktreeManager(repo_root)
                workspace = self.worktree_manager.create(
                    task_id=plan.task_id,
                    base_commit=plan.base_commit,
                    constitution=plan.constitution,
                )
                saga.add_compensation("delete_worktree", lambda: asyncio.to_thread(self.worktree_manager.cleanup, workspace))
                events.append(
                    self.event_store.append(
                        "worktree_created",
                        {"workspace": str(workspace), "task_id": plan.task_id, "cache_key": cache_key},
                    )
                )

            result = await self.executor.execute(plan, workspace)
            touched_files = result.touched_files or self._extract_patch_paths(result.patch)
            watcher.validate_paths(touched_files)
            self._apply_patch(workspace, result.patch)
            post_patch = self.verifier.run_post_patch(middle, workspace)
            verification = self.verifier.summarize(pre_patch=pre_patch, post_patch=post_patch)
            self.action_cache.put(frontend_ir, middle.constitution, patch=result.patch, verification_summary=verification)
            events.append(
                self.event_store.append(
                    "execution_completed",
                    {
                        "cache_key": cache_key,
                        "workspace": str(workspace),
                        "touched_files": touched_files,
                        "executor_metadata": result.metadata,
                    },
                )
            )
            return {
                **state,
                "cache_key": cache_key,
                "cache_hit": False,
                "workspace": workspace,
                "touched_files": touched_files,
                "verification": verification,
                "events": events,
            }
        except Exception as exc:
            compensation = await saga.compensate()
            events.append(
                self.event_store.append(
                    "compensation_completed",
                    {"cache_key": cache_key, "actions": compensation, "error": str(exc)},
                )
            )
            if isinstance(exc, PipelineFailure):
                raise
            raise PipelineFailure(str(exc)) from exc

    def _apply_patch(self, repo_root: Path, patch: str) -> None:
        if not patch.strip():
            return
        check = subprocess.run(
            ["git", "apply", "--check", "-"],
            cwd=repo_root,
            input=patch,
            text=True,
            capture_output=True,
            check=False,
        )
        if check.returncode == 0:
            process = subprocess.run(
                ["git", "apply", "--whitespace=nowarn", "-"],
                cwd=repo_root,
                input=patch,
                text=True,
                capture_output=True,
                check=False,
            )
            if process.returncode != 0:
                raise PipelineFailure(process.stderr.strip() or "failed to apply patch")
            return

        reverse = subprocess.run(
            ["git", "apply", "--reverse", "--check", "-"],
            cwd=repo_root,
            input=patch,
            text=True,
            capture_output=True,
            check=False,
        )
        if reverse.returncode == 0:
            return

        process = subprocess.run(
            ["git", "apply", "--whitespace=nowarn", "-"],
            cwd=repo_root,
            input=patch,
            text=True,
            capture_output=True,
            check=False,
        )
        if process.returncode != 0:
            raise PipelineFailure(process.stderr.strip() or "failed to apply patch")

    def _extract_patch_paths(self, patch: str) -> list[str]:
        paths: list[str] = []
        for line in patch.splitlines():
            if line.startswith("+++ b/"):
                path = line.removeprefix("+++ b/").strip()
                if path != "/dev/null":
                    paths.append(path)
        return sorted(set(paths))
