"""Remote compute runtime adapters and providers."""

from __future__ import annotations

import asyncio
import base64
import shlex
from abc import ABC, abstractmethod
from collections.abc import AsyncIterator
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from ..exceptions import PipelineFailure
from ..ir import ExecutionPlan
from ..monitor_backends import MonitorBackend, build_monitor_backend
from ..verifier import CommandResult, VerificationRunner
from ..worktree import WorktreeManager
from .base import RuntimeAdapter, RuntimeEvent, RuntimeSession


@dataclass(frozen=True)
class RemoteSandboxHandle:
    provider: str
    sandbox_id: str
    remote_root: str
    metadata: dict[str, Any] = field(default_factory=dict)
    raw: Any | None = field(default=None, compare=False, repr=False)


class RemoteSandboxProvider(ABC):
    name: str

    @abstractmethod
    async def create(self, *, plan: ExecutionPlan) -> RemoteSandboxHandle:
        raise NotImplementedError

    @abstractmethod
    async def destroy(self, handle: RemoteSandboxHandle) -> None:
        raise NotImplementedError

    @abstractmethod
    async def run_command(self, handle: RemoteSandboxHandle, command: list[str], cwd: str) -> CommandResult:
        raise NotImplementedError

    async def upload_workspace(self, handle: RemoteSandboxHandle, workspace: Path) -> dict[str, Any]:
        file_count = 0
        byte_count = 0
        for path in workspace.rglob("*"):
            if not path.is_file():
                continue
            rel_path = path.relative_to(workspace).as_posix()
            payload = base64.b64encode(path.read_bytes()).decode("ascii")
            remote_path = f"{handle.remote_root.rstrip('/')}/{rel_path}"
            script = "\n".join(
                [
                    "python3 - <<'PY'",
                    "import base64",
                    "from pathlib import Path",
                    f"target = Path({remote_path!r})",
                    "target.parent.mkdir(parents=True, exist_ok=True)",
                    f"target.write_bytes(base64.b64decode({payload!r}))",
                    "PY",
                ]
            )
            await self.run_command(handle, ["bash", "-lc", script], cwd=handle.remote_root)
            file_count += 1
            byte_count += path.stat().st_size
        return {"uploaded_files": file_count, "uploaded_bytes": byte_count, "remote_root": handle.remote_root}

    async def download_files(self, handle: RemoteSandboxHandle, workspace: Path, paths: list[str]) -> None:
        for rel_path in paths:
            remote_path = f"{handle.remote_root.rstrip('/')}/{rel_path}"
            script = "\n".join(
                [
                    "python3 - <<'PY'",
                    "import base64",
                    "from pathlib import Path",
                    f"target = Path({remote_path!r})",
                    "if target.exists():",
                    "    print(base64.b64encode(target.read_bytes()).decode('ascii'))",
                    "PY",
                ]
            )
            result = await self.run_command(handle, ["bash", "-lc", script], cwd=handle.remote_root)
            if result.exit_code != 0 or not result.stdout.strip():
                continue
            local_path = workspace / rel_path
            local_path.parent.mkdir(parents=True, exist_ok=True)
            local_path.write_bytes(base64.b64decode(result.stdout.strip()))

    async def stream_events(self, handle: RemoteSandboxHandle) -> AsyncIterator[RuntimeEvent]:
        del handle
        if False:
            yield RuntimeEvent(path="", action="")

    def telemetry(self, handle: RemoteSandboxHandle) -> dict[str, Any]:
        return {"provider": self.name, "sandbox_id": handle.sandbox_id, "remote_root": handle.remote_root, **handle.metadata}


class GenericRemoteRuntimeAdapter(RuntimeAdapter):
    """Creates a local worktree mirror and a remote sandbox provider session."""

    def __init__(
        self,
        repo_root: str | Path,
        *,
        provider: RemoteSandboxProvider,
        worktree_manager: WorktreeManager | None = None,
        fallback_monitor_backend: MonitorBackend | None = None,
    ) -> None:
        self.repo_root = Path(repo_root).resolve()
        self.provider = provider
        self.worktree_manager = worktree_manager or WorktreeManager(self.repo_root)
        self.fallback_monitor_backend = fallback_monitor_backend or build_monitor_backend()

    async def execute(self, plan: ExecutionPlan) -> RuntimeSession:
        workspace = self.worktree_manager.create(
            task_id=plan.task_id,
            base_commit=plan.base_commit,
            constitution=plan.constitution,
        )
        handle = await self.provider.create(plan=plan)
        try:
            upload_summary = await self.provider.upload_workspace(handle, workspace)
        except Exception:
            await self.provider.destroy(handle)
            self.worktree_manager.cleanup(workspace)
            raise
        return RuntimeSession(
            workspace=workspace,
            cleanup_token=handle.sandbox_id,
            telemetry={
                **self.provider.telemetry(handle),
                "mode": "remote-mirror",
                "monitor_backend": self.fallback_monitor_backend.name,
                "upload_summary": upload_summary,
            },
            opaque_state=handle,
        )

    async def compensate(self, session: RuntimeSession) -> None:
        handle = session.opaque_state
        if handle is not None:
            await self.provider.destroy(handle)
        await asyncio.to_thread(self.worktree_manager.cleanup, session.workspace)

    async def stream_events(self, session: RuntimeSession) -> AsyncIterator[RuntimeEvent]:
        handle = session.opaque_state
        emitted_remote_event = False
        if handle is not None:
            async for event in self.provider.stream_events(handle):
                emitted_remote_event = True
                yield event
        if emitted_remote_event:
            return
        async for event in self.fallback_monitor_backend.stream(
            session.workspace,
            details={"provider": self.provider.name},
        ):
            yield event

    def telemetry(self, session: RuntimeSession) -> dict[str, object]:
        return dict(session.telemetry)

    async def apply_patch(self, session: RuntimeSession, patch: str) -> None:
        handle = session.opaque_state
        if handle is None or not patch.strip():
            return
        payload = base64.b64encode(patch.encode("utf-8")).decode("ascii")
        script = "\n".join(
            [
                "python3 - <<'PY'",
                "import base64, subprocess",
                f"patch = base64.b64decode({payload!r}).decode('utf-8')",
                "result = subprocess.run(['git', 'apply', '--whitespace=nowarn', '-'], input=patch, text=True, capture_output=True)",
                "print(result.stdout, end='')",
                "print(result.stderr, end='') if result.returncode else None",
                "raise SystemExit(result.returncode)",
                "PY",
            ]
        )
        result = await self.provider.run_command(handle, ["bash", "-lc", script], cwd=handle.remote_root)
        if result.exit_code != 0:
            raise PipelineFailure(result.stderr.strip() or result.stdout.strip() or "failed to apply patch in remote sandbox")

    async def reverse_patch(self, session: RuntimeSession, patch: str) -> None:
        handle = session.opaque_state
        if handle is None or not patch.strip():
            return
        payload = base64.b64encode(patch.encode("utf-8")).decode("ascii")
        script = "\n".join(
            [
                "python3 - <<'PY'",
                "import base64, subprocess",
                f"patch = base64.b64decode({payload!r}).decode('utf-8')",
                "result = subprocess.run(['git', 'apply', '--reverse', '--whitespace=nowarn', '-'], input=patch, text=True, capture_output=True)",
                "print(result.stdout, end='')",
                "print(result.stderr, end='') if result.returncode else None",
                "raise SystemExit(result.returncode)",
                "PY",
            ]
        )
        result = await self.provider.run_command(handle, ["bash", "-lc", script], cwd=handle.remote_root)
        if result.exit_code != 0:
            raise PipelineFailure(result.stderr.strip() or result.stdout.strip() or "failed to reverse patch in remote sandbox")

    async def run_pre_patch_verification(
        self,
        session: RuntimeSession,
        verifier: VerificationRunner,
        plan: ExecutionPlan,
    ):
        handle = session.opaque_state
        if handle is None:
            return await super().run_pre_patch_verification(session, verifier, plan)
        return await verifier.run_pre_patch_async(
            plan,
            handle.remote_root,
            command_runner=lambda command, cwd: self.provider.run_command(handle, command, str(cwd)),
        )

    async def run_post_patch_verification(
        self,
        session: RuntimeSession,
        verifier: VerificationRunner,
        plan: ExecutionPlan,
    ):
        handle = session.opaque_state
        if handle is None:
            return await super().run_post_patch_verification(session, verifier, plan)
        return await verifier.run_post_patch_async(
            plan,
            handle.remote_root,
            command_runner=lambda command, cwd: self.provider.run_command(handle, command, str(cwd)),
        )

    async def sync_back_to_local(self, session: RuntimeSession, local_workspace: Path, file_paths: list[str]) -> None:
        handle = session.opaque_state
        if handle is None:
            return
        await self.provider.download_files(handle, local_workspace, file_paths)


class E2BSandboxProvider(RemoteSandboxProvider):
    name = "e2b"

    def __init__(self, *, remote_root: str = "/workspace") -> None:
        self.remote_root = remote_root
        try:
            from e2b import Sandbox  # type: ignore
        except Exception:
            Sandbox = None
        self._sandbox_class = Sandbox

    async def create(self, *, plan: ExecutionPlan) -> RemoteSandboxHandle:
        if self._sandbox_class is None:
            raise PipelineFailure("e2b SDK not installed")

        def _create():
            create = getattr(self._sandbox_class, "create", None)
            if callable(create):
                return create(timeout=plan.resource_limits.max_runtime_seconds)
            return self._sandbox_class(timeout=plan.resource_limits.max_runtime_seconds)

        sandbox = await asyncio.to_thread(_create)
        sandbox_id = (
            getattr(sandbox, "sandbox_id", None)
            or getattr(sandbox, "sandboxId", None)
            or getattr(sandbox, "id", None)
            or plan.task_id
        )
        return RemoteSandboxHandle(provider=self.name, sandbox_id=str(sandbox_id), remote_root=self.remote_root, raw=sandbox)

    async def destroy(self, handle: RemoteSandboxHandle) -> None:
        sandbox = handle.raw
        for method_name in ["kill", "terminate", "close"]:
            method = getattr(sandbox, method_name, None)
            if callable(method):
                await asyncio.to_thread(method)
                return

    async def run_command(self, handle: RemoteSandboxHandle, command: list[str], cwd: str) -> CommandResult:
        sandbox = handle.raw
        commands = getattr(sandbox, "commands", None)
        if commands is None or not hasattr(commands, "run"):
            raise PipelineFailure("e2b sandbox does not expose commands.run")

        def _run():
            if len(command) == 3 and command[:2] == ["bash", "-lc"]:
                return commands.run(command[2], cwd=cwd)
            return commands.run(" ".join(shlex.quote(part) for part in command), cwd=cwd)

        result = await asyncio.to_thread(_run)
        exit_code = getattr(result, "exit_code", 0)
        return CommandResult(
            command=command,
            exit_code=0 if exit_code is None else int(exit_code),
            stdout=getattr(result, "stdout", "") or "",
            stderr=getattr(result, "stderr", "") or "",
        )


class ModalSandboxProvider(RemoteSandboxProvider):
    name = "modal"

    def __init__(self, *, app_name: str = "research-compiler", remote_root: str = "/workspace") -> None:
        self.app_name = app_name
        self.remote_root = remote_root
        try:
            import modal  # type: ignore
        except Exception:
            modal = None
        self._modal = modal

    async def create(self, *, plan: ExecutionPlan) -> RemoteSandboxHandle:
        if self._modal is None:
            raise PipelineFailure("modal SDK not installed")

        def _create():
            app = self._modal.App.lookup(self.app_name, create_if_missing=True)
            sandbox = self._modal.Sandbox.create(
                "sleep",
                str(plan.resource_limits.max_runtime_seconds),
                app=app,
                timeout=plan.resource_limits.max_runtime_seconds,
                workdir=self.remote_root,
            )
            return sandbox

        sandbox = await asyncio.to_thread(_create)
        sandbox_id = getattr(sandbox, "object_id", None) or getattr(sandbox, "id", None) or plan.task_id
        return RemoteSandboxHandle(
            provider=self.name,
            sandbox_id=str(sandbox_id),
            remote_root=self.remote_root,
            metadata={"app_name": self.app_name},
            raw=sandbox,
        )

    async def destroy(self, handle: RemoteSandboxHandle) -> None:
        sandbox = handle.raw
        for method_name in ["terminate", "detach", "close"]:
            method = getattr(sandbox, method_name, None)
            if callable(method):
                await asyncio.to_thread(method)
                if method_name == "terminate":
                    continue
                return

    async def run_command(self, handle: RemoteSandboxHandle, command: list[str], cwd: str) -> CommandResult:
        sandbox = handle.raw
        exec_method = getattr(sandbox, "exec", None)
        if not callable(exec_method):
            raise PipelineFailure("modal sandbox does not expose exec")

        def _run():
            process = exec_method(*command, workdir=cwd)
            wait = getattr(process, "wait", None)
            if callable(wait):
                wait()
            return process

        process = await asyncio.to_thread(_run)
        returncode = getattr(process, "returncode", 0)
        stdout = getattr(process, "stdout", b"")
        stderr = getattr(process, "stderr", b"")
        if isinstance(stdout, bytes):
            stdout = stdout.decode("utf-8", errors="ignore")
        if isinstance(stderr, bytes):
            stderr = stderr.decode("utf-8", errors="ignore")
        return CommandResult(
            command=command,
            exit_code=0 if returncode is None else int(returncode),
            stdout=str(stdout),
            stderr=str(stderr),
        )


class E2BRuntimeAdapter(GenericRemoteRuntimeAdapter):
    def __init__(self, repo_root: str | Path, *, worktree_manager: WorktreeManager | None = None, fallback_monitor_backend: MonitorBackend | None = None) -> None:
        super().__init__(
            repo_root,
            provider=E2BSandboxProvider(),
            worktree_manager=worktree_manager,
            fallback_monitor_backend=fallback_monitor_backend,
        )


class ModalRuntimeAdapter(GenericRemoteRuntimeAdapter):
    def __init__(self, repo_root: str | Path, *, worktree_manager: WorktreeManager | None = None, fallback_monitor_backend: MonitorBackend | None = None) -> None:
        super().__init__(
            repo_root,
            provider=ModalSandboxProvider(),
            worktree_manager=worktree_manager,
            fallback_monitor_backend=fallback_monitor_backend,
        )
