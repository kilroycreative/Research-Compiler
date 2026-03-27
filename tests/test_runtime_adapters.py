from __future__ import annotations

import asyncio
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from core import DockerRuntimeAdapter, LocalRuntimeAdapter, PollingMonitorBackend, ResourceLimits, SandboxType, WorktreeManager
from core.adapters.base import RuntimeEvent, RuntimeSession
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
