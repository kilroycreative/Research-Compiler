"""Concurrent merge-queue style scheduler for pipeline tasks."""

from __future__ import annotations

import asyncio
from collections import defaultdict
from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from typing import Any

from .ir import ExecutionPlan
from .pipeline import PipelineRequest
from .vcs import VCSAdapter


@dataclass(frozen=True)
class QueueTask:
    task_id: str
    request: PipelineRequest
    commit_on_success: bool = False


@dataclass(frozen=True)
class QueueResult:
    task_id: str
    status: str
    workspace: str | None = None
    commit: str | None = None
    error: str | None = None


class MergeQueue:
    """Runs non-overlapping tasks concurrently and serializes overlapping file scopes."""

    def __init__(
        self,
        *,
        pipeline_factory: Callable[[], Any],
        max_parallel: int = 2,
        vcs_adapter: VCSAdapter | None = None,
    ) -> None:
        self.pipeline_factory = pipeline_factory
        self.max_parallel = max_parallel
        self.vcs_adapter = vcs_adapter or VCSAdapter()
        self._parallel = asyncio.Semaphore(max_parallel)
        self._file_locks: dict[str, asyncio.Lock] = defaultdict(asyncio.Lock)
        self._commit_lock = asyncio.Lock()

    async def run(self, tasks: list[QueueTask]) -> list[QueueResult]:
        coroutines = [self._run_task(task) for task in tasks]
        return await asyncio.gather(*coroutines)

    async def _run_task(self, task: QueueTask) -> QueueResult:
        lock_paths = sorted(set(task.request.authorized_files))
        locks = [self._file_locks[path] for path in lock_paths]
        async with self._parallel:
            for lock in locks:
                await lock.acquire()
            try:
                pipeline = self.pipeline_factory()
                result = await pipeline.run(task.request)
                commit = None
                if task.commit_on_success:
                    async with self._commit_lock:
                        commit = await asyncio.to_thread(
                            self.vcs_adapter.promote_commit,
                            result.workspace,
                            message=f"merge queue: {task.task_id}",
                        )
                return QueueResult(task_id=task.task_id, status="ok", workspace=result.workspace, commit=commit)
            except Exception as exc:
                return QueueResult(task_id=task.task_id, status="failed", error=str(exc))
            finally:
                for lock in reversed(locks):
                    lock.release()
