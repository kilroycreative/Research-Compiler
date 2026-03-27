"""HumanLayer-backed runtime adapter for BYO-sandbox session launch."""

from __future__ import annotations

import asyncio
import shutil
import subprocess
from collections.abc import AsyncIterator
from pathlib import Path

from ..exceptions import PipelineFailure
from ..ir import ExecutionPlan
from ..worktree import WorktreeManager
from .base import RuntimeAdapter, RuntimeEvent, RuntimeSession


class HumanLayerRuntimeAdapter(RuntimeAdapter):
    """Launches a HumanLayer/CodeLayer session inside a dedicated git worktree."""

    def __init__(
        self,
        repo_root: str | Path,
        *,
        worktree_manager: WorktreeManager | None = None,
        humanlayer_bin: str = "humanlayer",
        model: str | None = None,
        auto_launch: bool = True,
        extra_args: list[str] | None = None,
    ) -> None:
        self.repo_root = Path(repo_root).resolve()
        self.worktree_manager = worktree_manager or WorktreeManager(self.repo_root)
        self.humanlayer_bin = humanlayer_bin
        self.model = model
        self.auto_launch = auto_launch
        self.extra_args = extra_args or []

    async def execute(self, plan: ExecutionPlan) -> RuntimeSession:
        workspace = self.worktree_manager.create(
            task_id=plan.task_id,
            base_commit=plan.base_commit,
            constitution=plan.constitution,
        )
        if self.auto_launch and shutil.which(self.humanlayer_bin) is None:
            self.worktree_manager.cleanup(workspace)
            raise PipelineFailure(f"humanlayer binary not found: {self.humanlayer_bin}")

        model = self.model or plan.model_id
        prompt = self._build_launch_prompt(plan)
        cleanup_token = None
        if self.auto_launch:
            command = [
                self.humanlayer_bin,
                "launch",
                "-w",
                str(workspace),
                "-m",
                model,
                *self.extra_args,
                prompt,
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
                raise PipelineFailure(result.stderr.strip() or "failed to launch humanlayer session")
            cleanup_token = result.stdout.strip() or workspace.name

        return RuntimeSession(
            workspace=workspace,
            cleanup_token=cleanup_token,
            telemetry={
                "launcher": "humanlayer",
                "model": model,
                "auto_launch": self.auto_launch,
            },
        )

    async def compensate(self, session: RuntimeSession) -> None:
        await asyncio.to_thread(self.worktree_manager.cleanup, session.workspace)

    async def stream_events(self, session: RuntimeSession) -> AsyncIterator[RuntimeEvent]:
        del session
        if False:
            yield RuntimeEvent(path="", action="")

    def telemetry(self, session: RuntimeSession) -> dict[str, object]:
        return dict(session.telemetry)

    def _build_launch_prompt(self, plan: ExecutionPlan) -> str:
        return "\n".join(
            [
                f"Task ID: {plan.task_id}",
                "Authorized files:",
                *[f"- {path}" for path in plan.authorized_files],
                "Constitution:",
                plan.constitution,
                "Return a scoped patch only inside the authorized files.",
            ]
        )
