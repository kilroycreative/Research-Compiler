"""Docker-backed runtime adapter."""

from __future__ import annotations

import asyncio
import shutil
import subprocess
from collections.abc import AsyncIterator
from pathlib import Path

from ..exceptions import PipelineFailure
from ..ir import ExecutionPlan
from ..monitor_backends import MonitorBackend, build_monitor_backend
from ..worktree import WorktreeManager
from .base import RuntimeAdapter, RuntimeEvent, RuntimeSession


class DockerRuntimeAdapter(RuntimeAdapter):
    """Creates a worktree and a matching Docker container for isolated execution."""

    def __init__(
        self,
        repo_root: str | Path,
        *,
        image: str = "python:3.12-slim",
        worktree_manager: WorktreeManager | None = None,
        docker_bin: str = "docker",
        monitor_backend: MonitorBackend | None = None,
    ) -> None:
        self.repo_root = Path(repo_root).resolve()
        self.image = image
        self.worktree_manager = worktree_manager or WorktreeManager(self.repo_root)
        self.docker_bin = docker_bin
        self.monitor_backend = monitor_backend or build_monitor_backend()

    async def execute(self, plan: ExecutionPlan) -> RuntimeSession:
        if shutil.which(self.docker_bin) is None:
            raise PipelineFailure(f"docker binary not found: {self.docker_bin}")
        workspace = self.worktree_manager.create(
            task_id=plan.task_id,
            base_commit=plan.base_commit,
            constitution=plan.constitution,
        )
        container_name = f"factory-{plan.task_id.lower()}-{workspace.name}"
        command = [
            self.docker_bin,
            "run",
            "--detach",
            "--rm",
            "--name",
            container_name,
            "--network",
            "none",
            "--mount",
            f"type=bind,src={workspace},dst=/workspace",
            "--workdir",
            "/workspace",
            self.image,
            "sleep",
            str(plan.resource_limits.max_runtime_seconds),
        ]
        result = await asyncio.to_thread(
            subprocess.run,
            command,
            capture_output=True,
            text=True,
            check=False,
        )
        if result.returncode != 0:
            self.worktree_manager.cleanup(workspace)
            raise PipelineFailure(result.stderr.strip() or "failed to start docker runtime")
        container_id = result.stdout.strip()
        return RuntimeSession(
            workspace=workspace,
            cleanup_token=container_id,
            telemetry={"container_id": container_id, "container_name": container_name, "image": self.image},
        )

    async def compensate(self, session: RuntimeSession) -> None:
        if session.cleanup_token:
            await asyncio.to_thread(
                subprocess.run,
                [self.docker_bin, "rm", "-f", session.cleanup_token],
                capture_output=True,
                text=True,
                check=False,
            )
        await asyncio.to_thread(self.worktree_manager.cleanup, session.workspace)

    async def stream_events(self, session: RuntimeSession) -> AsyncIterator[RuntimeEvent]:
        async for event in self.monitor_backend.stream(
            session.workspace,
            details={"container_id": session.cleanup_token},
        ):
            yield event

    def telemetry(self, session: RuntimeSession) -> dict[str, object]:
        return {**session.telemetry, "monitor_backend": self.monitor_backend.name}
