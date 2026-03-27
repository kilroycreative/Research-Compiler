from __future__ import annotations

import asyncio
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from core import HumanLayerRuntimeAdapter, ResourceLimits, SandboxType, WorktreeManager
from core.ir import ExecutionPlan


class HumanLayerAdapterTests(unittest.TestCase):
    @patch("core.adapters.humanlayer.shutil.which", return_value="/usr/local/bin/humanlayer")
    @patch("core.adapters.humanlayer.subprocess.run")
    def test_humanlayer_adapter_launches_in_worktree(self, mock_run, _mock_which) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            repo = Path(tmp)
            (repo / ".git").mkdir()
            manager = FakeWorktreeManager(repo)
            mock_run.return_value = FakeCompletedProcess(0, "hl-run-123\n", "")
            adapter = HumanLayerRuntimeAdapter(repo, worktree_manager=manager, model="sonnet")
            session = asyncio.run(adapter.execute(self._plan()))
            self.assertEqual(session.cleanup_token, "hl-run-123")
            self.assertTrue(session.workspace.name.startswith("task"))
            asyncio.run(adapter.compensate(session))
            self.assertEqual(manager.cleaned, [session.workspace])

    @patch("core.adapters.humanlayer.shutil.which", return_value="/usr/local/bin/humanlayer")
    def test_humanlayer_adapter_can_skip_launch(self, _mock_which) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            repo = Path(tmp)
            (repo / ".git").mkdir()
            manager = FakeWorktreeManager(repo)
            adapter = HumanLayerRuntimeAdapter(repo, worktree_manager=manager, auto_launch=False)
            session = asyncio.run(adapter.execute(self._plan()))
            self.assertIsNone(session.cleanup_token)
            self.assertEqual(adapter.telemetry(session)["launcher"], "humanlayer")

    def _plan(self) -> ExecutionPlan:
        return ExecutionPlan(
            task_id="task",
            base_commit="abcdef1",
            authorized_files=["sample_app.py"],
            constitution="Scoped",
            verification_contracts=[{"kind": "pass_to_pass", "selectors": [{"selector": "tests"}]}],
            model_id="gpt-5",
            sandbox_type=SandboxType.WORKTREE,
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


if __name__ == "__main__":
    unittest.main()
