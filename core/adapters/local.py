"""Local/worktree runtime adapter."""

from __future__ import annotations

import asyncio
from collections.abc import AsyncIterator
from pathlib import Path

from ..ir import ExecutionPlan, SandboxType
from ..monitor_backends import MonitorBackend, build_monitor_backend
from ..worktree import WorktreeManager
from .base import RuntimeAdapter, RuntimeEvent, RuntimeSession


class LocalRuntimeAdapter(RuntimeAdapter):
    """Uses either the repo root or a content-addressed worktree as the runtime workspace."""

    def __init__(
        self,
        repo_root: str | Path,
        worktree_manager: WorktreeManager | None = None,
        monitor_backend: MonitorBackend | None = None,
    ) -> None:
        self.repo_root = Path(repo_root).resolve()
        self.worktree_manager = worktree_manager or WorktreeManager(self.repo_root)
        self.monitor_backend = monitor_backend or build_monitor_backend()

    async def execute(self, plan: ExecutionPlan) -> RuntimeSession:
        if plan.sandbox_type == SandboxType.WORKTREE:
            workspace = self.worktree_manager.create(
                task_id=plan.task_id,
                base_commit=plan.base_commit,
                constitution=plan.constitution,
            )
            return RuntimeSession(workspace=workspace, cleanup_token=str(workspace), telemetry={"mode": "worktree"})
        return RuntimeSession(workspace=self.repo_root, telemetry={"mode": "local"})

    async def compensate(self, session: RuntimeSession) -> None:
        if session.cleanup_token:
            await asyncio.to_thread(self.worktree_manager.cleanup, session.workspace)

    async def stream_events(self, session: RuntimeSession) -> AsyncIterator[RuntimeEvent]:
        async for event in self.monitor_backend.stream(session.workspace, details={"mode": "local"}):
            yield event

    def telemetry(self, session: RuntimeSession) -> dict[str, object]:
        return {**session.telemetry, "monitor_backend": self.monitor_backend.name}
