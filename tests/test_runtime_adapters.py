from __future__ import annotations

import asyncio
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from core import (
    DockerRuntimeAdapter,
    E2BSandboxProvider,
    GenericRemoteRuntimeAdapter,
    LocalRuntimeAdapter,
    PollingMonitorBackend,
    ResourceLimits,
    SandboxType,
    WorktreeManager,
)
from core.adapters.base import RuntimeEvent, RuntimeSession
from core.adapters.remote_compute import RemoteSandboxHandle, RemoteSandboxProvider
from core.ir import ExecutionPlan


class RuntimeAdapterTests(unittest.TestCase):
    def test_local_runtime_adapter_compensates_worktree(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            repo = Path(tmp)
            (repo / ".git").mkdir()
            manager = FakeWorktreeManager(repo)
            adapter = LocalRuntimeAdapter(repo, worktree_manager=manager)
            plan = self._plan(SandboxType.WORKTREE)
            session = asyncio.run(adapter.execute(plan))
            self.assertTrue(session.workspace.name.startswith("task"))
            asyncio.run(adapter.compensate(session))
            self.assertEqual(manager.cleaned, [session.workspace])
            self.assertEqual(adapter.telemetry(session)["monitor_backend"], "polling")

    @patch("core.adapters.docker.shutil.which", return_value="/usr/local/bin/docker")
    @patch("core.adapters.docker.subprocess.run")
    def test_docker_runtime_adapter_cleans_container_and_worktree(self, mock_run, _mock_which) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            repo = Path(tmp)
            (repo / ".git").mkdir()
            manager = FakeWorktreeManager(repo)
            adapter = DockerRuntimeAdapter(repo, worktree_manager=manager)

            mock_run.side_effect = [
                FakeCompletedProcess(0, "container-123\n", ""),
                FakeCompletedProcess(0, "", ""),
            ]
            session = asyncio.run(adapter.execute(self._plan(SandboxType.CONTAINER)))
            self.assertEqual(session.cleanup_token, "container-123")
            asyncio.run(adapter.compensate(session))
            self.assertEqual(manager.cleaned, [session.workspace])

    def test_local_runtime_adapter_uses_custom_monitor_backend(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            repo = Path(tmp)
            (repo / ".git").mkdir()
            adapter = LocalRuntimeAdapter(repo, worktree_manager=FakeWorktreeManager(repo), monitor_backend=PollingMonitorBackend())
            session = asyncio.run(adapter.execute(self._plan(SandboxType.LOCAL)))
            self.assertEqual(adapter.telemetry(session)["monitor_backend"], "polling")

    def test_remote_runtime_adapter_creates_provider_session_and_cleans_up(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            repo = Path(tmp)
            (repo / ".git").mkdir()
            (repo / "sample_app.py").write_text("print('hi')\n", encoding="utf-8")
            provider = FakeRemoteProvider()
            manager = FakeWorktreeManager(repo)
            adapter = GenericRemoteRuntimeAdapter(repo, provider=provider, worktree_manager=manager)

            session = asyncio.run(adapter.execute(self._plan(SandboxType.E2B)))
            self.assertEqual(session.cleanup_token, "sandbox-1")
            self.assertEqual(session.telemetry["provider"], "fake-remote")
            self.assertEqual(provider.upload_calls, 1)

            asyncio.run(adapter.compensate(session))
            self.assertEqual(provider.destroyed, ["sandbox-1"])
            self.assertEqual(manager.cleaned, [session.workspace])

    def test_remote_runtime_adapter_prefers_provider_events(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            repo = Path(tmp)
            (repo / ".git").mkdir()
            provider = FakeRemoteProvider(events=[RuntimeEvent(path="sample_app.py", action="modified")])
            adapter = GenericRemoteRuntimeAdapter(repo, provider=provider, worktree_manager=FakeWorktreeManager(repo))
            session = asyncio.run(adapter.execute(self._plan(SandboxType.E2B)))

            async def collect() -> list[RuntimeEvent]:
                events: list[RuntimeEvent] = []
                async for event in adapter.stream_events(session):
                    events.append(event)
                    break
                return events

            events = asyncio.run(collect())
            self.assertEqual(events[0].path, "sample_app.py")
            self.assertEqual(events[0].details["provider"], "fake-remote")

    def test_e2b_provider_requires_sdk(self) -> None:
        provider = E2BSandboxProvider()
        provider._sandbox_class = None
        with self.assertRaisesRegex(Exception, "e2b SDK not installed"):
            asyncio.run(provider.create(plan=self._plan(SandboxType.E2B)))

    def _plan(self, sandbox_type: SandboxType) -> ExecutionPlan:
        return ExecutionPlan(
            task_id="task",
            base_commit="abcdef1",
            authorized_files=["sample_app.py"],
            constitution="Scoped",
            verification_contracts=[{"kind": "pass_to_pass", "selectors": [{"selector": "tests"}]}],
            model_id="gpt-5",
            sandbox_type=sandbox_type,
            resource_limits=ResourceLimits(max_runtime_seconds=30, max_memory_mb=128),
        )


class FakeWorktreeManager(WorktreeManager):
    def __init__(self, repo_root: Path) -> None:
        self.repo_root = repo_root
        self.cleaned: list[Path] = []

    def create(self, *, task_id: str, base_commit: str, constitution: str) -> Path:
        del base_commit, constitution
        workspace = self.repo_root / f"{task_id}-workspace"
        workspace.mkdir(parents=True, exist_ok=True)
        return workspace

    def cleanup(self, path: str | Path) -> None:
        self.cleaned.append(Path(path))


class FakeCompletedProcess:
    def __init__(self, returncode: int, stdout: str, stderr: str) -> None:
        self.returncode = returncode
        self.stdout = stdout
        self.stderr = stderr


class FakeRemoteProvider(RemoteSandboxProvider):
    name = "fake-remote"

    def __init__(self, events: list[RuntimeEvent] | None = None) -> None:
        self.events = events or []
        self.upload_calls = 0
        self.destroyed: list[str] = []

    async def create(self, *, plan: ExecutionPlan) -> RemoteSandboxHandle:
        return RemoteSandboxHandle(provider=self.name, sandbox_id="sandbox-1", remote_root="/workspace", metadata={"task": plan.task_id})

    async def destroy(self, handle: RemoteSandboxHandle) -> None:
        self.destroyed.append(handle.sandbox_id)

    async def run_shell(self, handle: RemoteSandboxHandle, script: str) -> None:
        del handle, script

    async def upload_workspace(self, handle: RemoteSandboxHandle, workspace: Path) -> dict[str, object]:
        del handle, workspace
        self.upload_calls += 1
        return {"uploaded_files": 1, "uploaded_bytes": 12, "remote_root": "/workspace"}

    async def stream_events(self, handle: RemoteSandboxHandle):
        for event in self.events:
            yield RuntimeEvent(path=event.path, action=event.action, details={"provider": self.name})
            await asyncio.sleep(0)


class StreamingLocalAdapter(LocalRuntimeAdapter):
    def __init__(self, repo_root: Path, events: list[RuntimeEvent], worktree_manager: WorktreeManager | None = None) -> None:
        super().__init__(repo_root, worktree_manager=worktree_manager)
        self._events = events

    async def stream_events(self, session: RuntimeSession):
        for event in self._events:
            yield event
            await asyncio.sleep(0)


if __name__ == "__main__":
    unittest.main()
