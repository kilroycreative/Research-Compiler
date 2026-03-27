"""Async compiler pipeline with passes, cache replay, verification, and compensation."""

from __future__ import annotations

import asyncio
import time
from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from pydantic import BaseModel, ConfigDict, Field

from .action_cache import ActionCache
from .adapters import (
    DockerRuntimeAdapter,
    E2BRuntimeAdapter,
    LocalRuntimeAdapter,
    ModalRuntimeAdapter,
    RuntimeAdapter,
    RuntimeSession,
)
from .diagnostics import SourceMapper, TaskSummaryWriter
from .events import EventStore
from .execution_types import ExecutionResult
from .executors import ExecutorConfig
from .exceptions import PipelineFailure, PipelineStateCarrier, VerificationFailure
from .ir import ExecutionPlan, FrontendIR, MiddleEndIR, ResourceConstraints, ResourceLimits, SandboxType, VerificationContract
from .linker import Linker
from .monitor import RuntimeMonitor, run_with_monitor
from .optimizer_cache import OptimizerCache
from .saga import Saga
from .slicing import ContextPruner
from .symbols import SymbolTableBuilder
from .verifier import VerificationRunner
from .vcs import VCSAdapter
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
    resource_constraints: ResourceConstraints = Field(default_factory=ResourceConstraints)


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
        symbol_table_builder: SymbolTableBuilder | None = None,
        linker: Linker | None = None,
        context_pruner: ContextPruner | None = None,
        optimizer_cache: OptimizerCache | None = None,
        runtime_adapter: RuntimeAdapter | None = None,
        runtime_monitor: RuntimeMonitor | None = None,
        vcs_adapter: VCSAdapter | None = None,
        source_mapper: SourceMapper | None = None,
    ) -> None:
        self.executor = executor
        self.action_cache = action_cache
        self.verifier = verifier
        self.event_store = event_store
        self.worktree_manager = worktree_manager
        self.symbol_table_builder = symbol_table_builder or SymbolTableBuilder()
        self.linker = linker or Linker()
        self.context_pruner = context_pruner or ContextPruner()
        self.optimizer_cache = optimizer_cache
        self.runtime_adapter = runtime_adapter
        self.runtime_monitor = runtime_monitor
        self.vcs_adapter = vcs_adapter or VCSAdapter()
        self.source_mapper = source_mapper or SourceMapper()

    async def run(self, request: PipelineRequest) -> PipelineRunResult:
        started_at = time.time()
        manager = PassManager()
        manager.add("frontend", self._pass_frontend)
        manager.add("middle_end", self._pass_middle_end)
        manager.add("optimize_context", self._pass_optimize_context)
        manager.add("execution_plan", self._pass_execution_plan)
        manager.add("execute_or_replay", self._pass_execute_or_replay)

        try:
            state = await manager.run({"request": request})
            result = PipelineRunResult(
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
            self._write_summary(
                request=request,
                result=result,
                duration_seconds=time.time() - started_at,
                status="success",
                error=None,
            )
            return result
        except PipelineFailure as exc:
            state = getattr(exc, "pipeline_state", {"events": []})
            result = self._result_from_failure_state(request, state)
            self._write_summary(
                request=request,
                result=result,
                duration_seconds=time.time() - started_at,
                status="failed",
                error=str(exc),
            )
            raise

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
            resource_constraints=request.resource_constraints,
        )
        event = self.event_store.append(
            "execution_plan_lowered",
            {"task_id": plan.task_id, "sandbox_type": plan.sandbox_type, "model_id": plan.model_id},
        )
        return {**state, "execution_plan": plan, "events": [*state["events"], event]}

    async def _pass_optimize_context(self, state: dict[str, Any]) -> dict[str, Any]:
        request: PipelineRequest = state["request"]
        middle: MiddleEndIR = state["middle_end_ir"]
        cache_key: str | None = None
        cached = None
        if self.optimizer_cache is not None:
            cache_key = self.optimizer_cache.compute_key(request.repo_root, middle.authorized_files, middle.constitution)
            cached = self.optimizer_cache.get(cache_key)
        if cached is not None:
            symbol_table = cached["symbol_table"]
            linker_map = cached["linker_map"]
            context_slices = cached["context_slices"]
            cache_status = "hit"
        else:
            symbol_table = self.symbol_table_builder.build(request.repo_root, middle.authorized_files)
            linker_map = self.linker.build(request.repo_root, middle.authorized_files, symbol_table)
            context_slices = self.context_pruner.build(request.repo_root, middle.authorized_files, symbol_table, linker_map)
            if self.optimizer_cache is not None and cache_key is not None:
                self.optimizer_cache.put(
                    cache_key,
                    symbol_table=symbol_table,
                    linker_map=linker_map,
                    context_slices=context_slices,
                )
            cache_status = "miss"
        optimized = middle.model_copy(
            update={
                "symbol_table": symbol_table,
                "linker_map": linker_map,
                "context_slices": context_slices,
            }
        )
        event = self.event_store.append(
            "context_optimized",
            {
                "task_id": optimized.task_id,
                "symbol_count": len(symbol_table),
                "linked_symbol_count": len(linker_map),
                "slice_count": len(context_slices),
                "cache_status": cache_status,
            },
        )
        return {**state, "middle_end_ir": optimized, "events": [*state["events"], event]}

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
            self.vcs_adapter.apply_patch(repo_root, cached.patch)
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

        pre_patch = None

        saga = Saga()
        dispatcher = self.executor if hasattr(self.executor, "next_attempt_plan") else None
        attempt = 1
        attempt_plan = plan
        total_cost = 0.0
        stable_point = self.vcs_adapter.snapshot_stable(repo_root)
        try:
            while True:
                workspace = repo_root
                runtime_adapter = self._resolve_runtime_adapter(attempt_plan, repo_root)
                runtime_session = await runtime_adapter.execute(attempt_plan)
                workspace = runtime_session.workspace
                saga.add_compensation("runtime_compensate", lambda rs=runtime_session, ra=runtime_adapter: ra.compensate(rs))
                events.append(
                    self.event_store.append(
                        "runtime_prepared",
                        {
                            "workspace": str(workspace),
                            "task_id": attempt_plan.task_id,
                            "cache_key": cache_key,
                            "telemetry": runtime_adapter.telemetry(runtime_session),
                            "attempt": attempt,
                            "tier": attempt_plan.resource_constraints.model_tier,
                        },
                    )
                )

                monitor = self.runtime_monitor or RuntimeMonitor(watcher)
                if pre_patch is None:
                    pre_patch = await runtime_adapter.run_pre_patch_verification(runtime_session, self.verifier, middle)
                    events.append(
                        self.event_store.append("verification_pre_patch", {"count": len(pre_patch), "cache_key": cache_key})
                    )

                async def on_runtime_event(event) -> None:
                    events.append(
                        self.event_store.append(
                            "runtime_event",
                            {"path": event.path, "action": event.action, "details": event.details},
                        )
                    )

                result = await run_with_monitor(
                    self.executor.execute(attempt_plan, workspace),
                    monitor=monitor,
                    runtime_adapter=runtime_adapter,
                    session=runtime_session,
                    on_event=on_runtime_event,
                )
                touched_files = result.touched_files or self._extract_patch_paths(result.patch)
                watcher.validate_paths(touched_files)
                await runtime_adapter.apply_patch(runtime_session, result.patch)
                total_cost += float(result.metadata.get("cost_usd", 0.0))
                try:
                    post_patch = await runtime_adapter.run_post_patch_verification(runtime_session, self.verifier, middle)
                    verification = self.verifier.summarize(pre_patch=pre_patch, post_patch=post_patch)
                except VerificationFailure:
                    await runtime_adapter.reverse_patch(runtime_session, result.patch)
                    self.vcs_adapter.revert_to_stable(stable_point)
                    await runtime_adapter.compensate(runtime_session)
                    next_plan = (
                        dispatcher.next_attempt_plan(attempt_plan, attempt=attempt, spent_cost=total_cost)
                        if dispatcher is not None
                        else None
                    )
                    events.append(
                        self.event_store.append(
                            "dispatch_attempt",
                            {
                                "attempt": attempt,
                                "tier": str(attempt_plan.resource_constraints.model_tier),
                                "cost_usd": result.metadata.get("cost_usd", 0.0),
                                "status": "verification_failed",
                            },
                        )
                    )
                    if next_plan is None:
                        raise
                    attempt += 1
                    attempt_plan = next_plan
                    continue

                await runtime_adapter.sync_back_to_local(runtime_session, workspace, touched_files)
                self.vcs_adapter.apply_patch(workspace, result.patch)
                self.action_cache.put(frontend_ir, middle.constitution, patch=result.patch, verification_summary=verification)
                events.append(
                    self.event_store.append(
                        "dispatch_attempt",
                        {
                            "attempt": attempt,
                            "tier": str(attempt_plan.resource_constraints.model_tier),
                            "cost_usd": result.metadata.get("cost_usd", 0.0),
                            "status": "verified",
                        },
                    )
                )
                events.append(
                    self.event_store.append(
                        "execution_completed",
                        {
                            "cache_key": cache_key,
                            "workspace": str(workspace),
                            "touched_files": touched_files,
                            "executor_metadata": result.metadata,
                            "total_cost_usd": total_cost,
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
            diagnostic = self.source_mapper.map_to_slice(
                touched_files=[],
                context_slices=middle.context_slices,
                pass_name=state.get("current_pass", "execute_or_replay"),
                message=str(exc),
            )
            events.append(self.event_store.append("diagnostic", diagnostic.to_payload()))
            compensation = await saga.compensate()
            events.append(
                self.event_store.append(
                    "compensation_completed",
                    {"cache_key": cache_key, "actions": compensation, "error": str(exc)},
                )
            )
            failure_state = {
                **state,
                "cache_key": cache_key,
                "cache_hit": False,
                "workspace": repo_root,
                "touched_files": [],
                "verification": {},
                "events": events,
            }
            if isinstance(exc, PipelineFailure):
                setattr(exc, "pipeline_state", failure_state)
                raise
            wrapped = PipelineStateCarrier(str(exc))
            setattr(wrapped, "pipeline_state", failure_state)
            raise wrapped from exc

    def _resolve_runtime_adapter(self, plan: ExecutionPlan, repo_root: Path) -> RuntimeAdapter:
        if self.runtime_adapter is not None:
            return self.runtime_adapter
        if plan.sandbox_type == SandboxType.CONTAINER:
            return DockerRuntimeAdapter(repo_root, worktree_manager=self.worktree_manager)
        if plan.sandbox_type == SandboxType.E2B:
            return E2BRuntimeAdapter(repo_root, worktree_manager=self.worktree_manager)
        if plan.sandbox_type == SandboxType.MODAL:
            return ModalRuntimeAdapter(repo_root, worktree_manager=self.worktree_manager)
        return LocalRuntimeAdapter(repo_root, worktree_manager=self.worktree_manager)

    def _reverse_patch(self, repo_root: Path, patch: str) -> None:
        if not patch.strip():
            return
        process = subprocess.run(
            ["git", "apply", "--reverse", "--whitespace=nowarn", "-"],
            cwd=repo_root,
            input=patch,
            text=True,
            capture_output=True,
            check=False,
        )
        if process.returncode != 0:
            raise PipelineFailure(process.stderr.strip() or "failed to reverse patch")

    def _extract_patch_paths(self, patch: str) -> list[str]:
        paths: list[str] = []
        for line in patch.splitlines():
            if line.startswith("+++ b/"):
                path = line.removeprefix("+++ b/").strip()
                if path != "/dev/null":
                    paths.append(path)
        return sorted(set(paths))

    def _result_from_failure_state(self, request: PipelineRequest, state: dict[str, Any]) -> PipelineRunResult:
        frontend_ir = state.get(
            "frontend_ir",
            FrontendIR(task_id=request.task_id, base_commit=request.base_commit, authorized_files=request.authorized_files),
        )
        middle_end_ir = state.get(
            "middle_end_ir",
            MiddleEndIR(
                **frontend_ir.model_dump(mode="json"),
                constitution=request.constitution,
                verification_contracts=request.verification_contracts,
            ),
        )
        execution_plan = state.get(
            "execution_plan",
            ExecutionPlan(
                **middle_end_ir.model_dump(mode="json"),
                model_id=request.model_id,
                sandbox_type=request.sandbox_type,
                resource_limits=request.resource_limits,
                resource_constraints=request.resource_constraints,
            ),
        )
        return PipelineRunResult(
            frontend_ir=frontend_ir,
            middle_end_ir=middle_end_ir,
            execution_plan=execution_plan,
            cache_key=state.get("cache_key", self.action_cache.compute_action_key(frontend_ir, middle_end_ir.constitution)),
            cache_hit=bool(state.get("cache_hit", False)),
            workspace=str(state.get("workspace", Path(request.repo_root).resolve())),
            touched_files=list(state.get("touched_files", [])),
            verification=dict(state.get("verification", {})),
            events=list(state.get("events", [])),
        )

    def _write_summary(
        self,
        *,
        request: PipelineRequest,
        result: PipelineRunResult,
        duration_seconds: float,
        status: str,
        error: str | None,
    ) -> None:
        summary_path = Path(request.repo_root).resolve() / ".pipeline" / request.task_id / "summary.json"
        writer = TaskSummaryWriter(summary_path)
        diagnostics = [event["payload"] for event in result.events if event["event_type"] == "diagnostic"]
        dispatch = [event["payload"] for event in result.events if event["event_type"] == "dispatch_attempt"]
        writer.write(
            {
                "task_id": request.task_id,
                "status": status,
                "cache_hit": result.cache_hit,
                "workspace": result.workspace,
                "touched_files": result.touched_files,
                "verification": result.verification,
                "duration_seconds": round(duration_seconds, 6),
                "dispatch_attempts": dispatch,
                "total_cost_usd": sum(float(item.get("cost_usd", 0.0)) for item in dispatch),
                "diagnostics": diagnostics,
                "error": error,
            }
        )
