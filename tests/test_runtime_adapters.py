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
from core.verifier import CommandResult, VerificationRunner
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

    def test_remote_runtime_adapter_runs_verification_and_syncs_back(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            repo = Path(tmp)
            (repo / ".git").mkdir()
            workspace = repo / "task-workspace"
            workspace.mkdir()
            (workspace / "sample_app.py").write_text("def value():\n    return 1\n", encoding="utf-8")
            provider = FakeRemoteProvider(file_map={"sample_app.py": "def value():\n    return 2\n"})
            adapter = GenericRemoteRuntimeAdapter(repo, provider=provider, worktree_manager=FakeWorktreeManager(repo))
            session = asyncio.run(adapter.execute(self._plan(SandboxType.E2B)))
            verifier = VerificationRunner()
            plan = self._plan(SandboxType.E2B)

            asyncio.run(adapter.apply_patch(session, SAMPLE_PATCH))
            pre = asyncio.run(adapter.run_pre_patch_verification(session, verifier, plan))
            post = asyncio.run(adapter.run_post_patch_verification(session, verifier, plan))
            asyncio.run(adapter.sync_back_to_local(session, session.workspace, ["sample_app.py"]))

            self.assertEqual(len(pre), 0)
            self.assertEqual(len(post), 1)
            self.assertIn("subprocess.run(['git', 'apply'", " ".join(provider.command_log[0]))
            self.assertIn("pytest", " ".join(provider.command_log[1]))
            self.assertIn("return 2", (session.workspace / "sample_app.py").read_text(encoding="utf-8"))

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

    def __init__(self, events: list[RuntimeEvent] | None = None, file_map: dict[str, str] | None = None) -> None:
        self.events = events or []
        self.file_map = file_map or {}
        self.upload_calls = 0
        self.destroyed: list[str] = []
        self.command_log: list[list[str]] = []

    async def create(self, *, plan: ExecutionPlan) -> RemoteSandboxHandle:
        return RemoteSandboxHandle(provider=self.name, sandbox_id="sandbox-1", remote_root="/workspace", metadata={"task": plan.task_id})

    async def destroy(self, handle: RemoteSandboxHandle) -> None:
        self.destroyed.append(handle.sandbox_id)

    async def run_command(self, handle: RemoteSandboxHandle, command: list[str], cwd: str) -> CommandResult:
        del handle, cwd
        self.command_log.append(command)
        joined = " ".join(command)
        if "git apply" in joined:
            return CommandResult(command=command, exit_code=0, stdout="", stderr="")
        if command[:1] == ["pytest"]:
            return CommandResult(command=command, exit_code=0, stdout="ok", stderr="")
        if "base64.b64encode" in joined and self.file_map:
            encoded = next(iter(self.file_map.values())).encode("utf-8")
            import base64

            return CommandResult(command=command, exit_code=0, stdout=base64.b64encode(encoded).decode("ascii"), stderr="")
        return CommandResult(command=command, exit_code=0, stdout="", stderr="")

    async def upload_workspace(self, handle: RemoteSandboxHandle, workspace: Path) -> dict[str, object]:
        del handle, workspace
        self.upload_calls += 1
        return {"uploaded_files": 1, "uploaded_bytes": 12, "remote_root": "/workspace"}

    async def stream_events(self, handle: RemoteSandboxHandle):
        for event in self.events:
            yield RuntimeEvent(path=event.path, action=event.action, details={"provider": self.name})
            await asyncio.sleep(0)


SAMPLE_PATCH = """diff --git a/sample_app.py b/sample_app.py
index 1c02a8f..75db990 100644
--- a/sample_app.py
+++ b/sample_app.py
@@ -1,2 +1,2 @@
 def value():
-    return 1
+    return 2
"""


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
