"""Runtime adapter base interfaces."""

from __future__ import annotations

import asyncio
import subprocess
from abc import ABC, abstractmethod
from collections.abc import AsyncIterator
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from ..exceptions import PipelineFailure
from ..ir import ExecutionPlan
from ..verifier import VerificationRunner


@dataclass(frozen=True)
class RuntimeSession:
    workspace: Path
    telemetry: dict[str, Any] = field(default_factory=dict)
    cleanup_token: str | None = None
    opaque_state: Any | None = field(default=None, compare=False, repr=False)


@dataclass(frozen=True)
class RuntimeEvent:
    path: str
    action: str
    timestamp: float | None = None
    details: dict[str, Any] = field(default_factory=dict)


class RuntimeAdapter(ABC):
    """Impure runtime boundary for isolated execution environments."""

    @abstractmethod
    async def execute(self, plan: ExecutionPlan) -> RuntimeSession:
        raise NotImplementedError

    @abstractmethod
    async def compensate(self, session: RuntimeSession) -> None:
        raise NotImplementedError

    @abstractmethod
    async def stream_events(self, session: RuntimeSession) -> AsyncIterator[RuntimeEvent]:
        raise NotImplementedError

    @abstractmethod
    def telemetry(self, session: RuntimeSession) -> dict[str, Any]:
        raise NotImplementedError

    async def apply_patch(self, session: RuntimeSession, patch: str) -> None:
        await asyncio.to_thread(_git_apply, session.workspace, patch, reverse=False)

    async def reverse_patch(self, session: RuntimeSession, patch: str) -> None:
        await asyncio.to_thread(_git_apply, session.workspace, patch, reverse=True)

    async def run_pre_patch_verification(
        self,
        session: RuntimeSession,
        verifier: VerificationRunner,
        plan: ExecutionPlan,
    ):
        return await asyncio.to_thread(verifier.run_pre_patch, plan, session.workspace)

    async def run_post_patch_verification(
        self,
        session: RuntimeSession,
        verifier: VerificationRunner,
        plan: ExecutionPlan,
    ):
        return await asyncio.to_thread(verifier.run_post_patch, plan, session.workspace)

    async def sync_back_to_local(self, session: RuntimeSession, local_workspace: Path, file_paths: list[str]) -> None:
        del session, local_workspace, file_paths


def _git_apply(workspace: Path, patch: str, *, reverse: bool) -> None:
    if not patch.strip():
        return
    command = ["git", "apply", "--whitespace=nowarn"]
    if reverse:
        command.append("--reverse")
    command.append("-")
    process = subprocess.run(
        command,
        cwd=workspace,
        input=patch,
        text=True,
        capture_output=True,
        check=False,
    )
    if process.returncode != 0:
        raise PipelineFailure(process.stderr.strip() or "failed to apply runtime patch")
