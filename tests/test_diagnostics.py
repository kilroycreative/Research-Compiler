from __future__ import annotations

import json
import subprocess
import tempfile
import unittest
from pathlib import Path

from core import ActionCache, EventStore, Pipeline, PipelineRequest, ResourceConstraints, ResourceLimits, SandboxType, VerificationFailure, VerificationRunner
from core.execution_types import ExecutionResult
from core.ir import ModelTier


class BadExecutor:
    async def execute(self, plan, workspace):
        del plan, workspace
        patch = """diff --git a/sample_app.py b/sample_app.py
index 1c02a8f..75db990 100644
--- a/sample_app.py
+++ b/sample_app.py
@@ -1,2 +1,2 @@
 def value():
-    return 1
+    return 3
"""
        return ExecutionResult(
            patch=patch,
            touched_files=["sample_app.py"],
            metadata={"prompt_tokens": 100, "completion_tokens": 50, "cost_usd": 0.01},
        )


class GoodExecutor:
    async def execute(self, plan, workspace):
        del plan, workspace
        patch = """diff --git a/sample_app.py b/sample_app.py
index 1c02a8f..75db990 100644
--- a/sample_app.py
+++ b/sample_app.py
@@ -1,2 +1,2 @@
 def value():
-    return 1
+    return 2
"""
        return ExecutionResult(
            patch=patch,
            touched_files=["sample_app.py"],
            metadata={"prompt_tokens": 120, "completion_tokens": 60, "cost_usd": 0.02},
        )


class DiagnosticsTests(unittest.IsolatedAsyncioTestCase):
    async def test_summary_json_written_for_successful_run(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            repo = self._init_repo(Path(tmp))
            base_commit = self._commit_all(repo)
            pipeline = Pipeline(
                executor=GoodExecutor(),
                action_cache=ActionCache(repo / "action_cache.db"),
                verifier=VerificationRunner(),
                event_store=EventStore(repo / "events.jsonl"),
            )
            request = PipelineRequest(
                task_id="task",
                base_commit=base_commit,
                authorized_files=["sample_app.py"],
                constitution="Keep fix scoped",
                verification_contracts=[
                    {"kind": "fail_to_pass", "selectors": [{"selector": "test_app.py::test_bug"}]},
                    {"kind": "pass_to_pass", "selectors": [{"selector": "test_app.py::test_bug"}]},
                ],
                model_id="gpt-5",
                repo_root=str(repo),
                sandbox_type=SandboxType.LOCAL,
                resource_limits=ResourceLimits(max_runtime_seconds=60, max_memory_mb=256),
                resource_constraints=ResourceConstraints(model_tier=ModelTier.PRODUCTION),
            )
            await pipeline.run(request)
            summary = json.loads((repo / ".pipeline" / "task" / "summary.json").read_text(encoding="utf-8"))
            self.assertEqual(summary["task_id"], "task")
            self.assertGreaterEqual(summary["duration_seconds"], 0)
            self.assertEqual(summary["touched_files"], ["sample_app.py"])

    async def test_diagnostic_emitted_on_failure(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            repo = self._init_repo(Path(tmp))
            base_commit = self._commit_all(repo)
            pipeline = Pipeline(
                executor=BadExecutor(),
                action_cache=ActionCache(repo / "action_cache.db"),
                verifier=VerificationRunner(),
                event_store=EventStore(repo / "events.jsonl"),
            )
            request = PipelineRequest(
                task_id="task",
                base_commit=base_commit,
                authorized_files=["sample_app.py"],
                constitution="Keep fix scoped",
                verification_contracts=[
                    {"kind": "fail_to_pass", "selectors": [{"selector": "test_app.py::test_bug"}]},
                    {"kind": "pass_to_pass", "selectors": [{"selector": "test_app.py::test_bug"}]},
                ],
                model_id="gpt-5",
                repo_root=str(repo),
                sandbox_type=SandboxType.LOCAL,
                resource_limits=ResourceLimits(max_runtime_seconds=60, max_memory_mb=256),
                resource_constraints=ResourceConstraints(model_tier=ModelTier.PRODUCTION, allow_escalation=False),
            )
            with self.assertRaises(VerificationFailure):
                await pipeline.run(request)
            events = EventStore(repo / "events.jsonl").read_all()
            self.assertIn("diagnostic", [event["event_type"] for event in events])

    def _init_repo(self, root: Path) -> Path:
        subprocess.run(["git", "init"], cwd=root, check=True, capture_output=True, text=True)
        subprocess.run(["git", "config", "user.email", "test@example.com"], cwd=root, check=True)
        subprocess.run(["git", "config", "user.name", "Test User"], cwd=root, check=True)
        (root / "sample_app.py").write_text("def value():\n    return 1\n", encoding="utf-8")
        (root / "test_app.py").write_text("from sample_app import value\n\ndef test_bug():\n    assert value() == 2\n", encoding="utf-8")
        return root

    def _commit_all(self, root: Path) -> str:
        subprocess.run(["git", "add", "."], cwd=root, check=True)
        subprocess.run(["git", "commit", "-m", "initial"], cwd=root, check=True, capture_output=True, text=True)
        return subprocess.run(["git", "rev-parse", "HEAD"], cwd=root, check=True, capture_output=True, text=True).stdout.strip()


if __name__ == "__main__":
    unittest.main()
