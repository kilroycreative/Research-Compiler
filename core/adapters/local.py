"""Local/worktree runtime adapter."""

from __future__ import annotations

import asyncio
import time
from collections.abc import AsyncIterator
from pathlib import Path

from ..ir import ExecutionPlan, SandboxType
from ..worktree import WorktreeManager
from .base import RuntimeAdapter, RuntimeEvent, RuntimeSession


class LocalRuntimeAdapter(RuntimeAdapter):
    """Uses either the repo root or a content-addressed worktree as the runtime workspace."""

    def __init__(self, repo_root: str | Path, worktree_manager: WorktreeManager | None = None) -> None:
        self.repo_root = Path(repo_root).resolve()
        self.worktree_manager = worktree_manager or WorktreeManager(self.repo_root)

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
        mtimes: dict[Path, int] = {}
        while True:
            for path in session.workspace.rglob("*"):
                if path.is_dir():
                    continue
                try:
                    stat = path.stat()
                except FileNotFoundError:
                    continue
                current = stat.st_mtime_ns
                previous = mtimes.get(path)
                mtimes[path] = current
                if previous is None:
                    continue
                if current != previous:
                    yield RuntimeEvent(
                        path=path.relative_to(session.workspace).as_posix(),
                        action="modified",
                        timestamp=time.time(),
                    )
            await asyncio.sleep(0.05)

    def telemetry(self, session: RuntimeSession) -> dict[str, object]:
        return dict(session.telemetry)
