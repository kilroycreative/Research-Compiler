from __future__ import annotations

import asyncio
import json
import subprocess
import tempfile
import unittest
from pathlib import Path

from core import (
    ActionCache,
    AuthorizedWriteWatcher,
    EventStore,
    FrontendIR,
    PassManager,
    Pipeline,
    PipelineFailure,
    PipelineRequest,
    ResourceLimits,
    Saga,
    SandboxType,
    SecurityViolation,
    VerificationRunner,
)
from core.pipeline import ExecutionResult


class FakeExecutor:
    def __init__(self, patch: str, touched_files: list[str], metadata: dict | None = None) -> None:
        self.patch = patch
        self.touched_files = touched_files
        self.metadata = metadata or {}
        self.calls = 0

    async def execute(self, plan, workspace):
        self.calls += 1
        return ExecutionResult(patch=self.patch, touched_files=self.touched_files, metadata=self.metadata)


class RuntimeTests(unittest.IsolatedAsyncioTestCase):
    async def test_pass_manager_preserves_order(self) -> None:
        manager = PassManager()
        order: list[str] = []

        async def first(state):
            order.append("first")
            return {**state, "a": 1}

        async def second(state):
            order.append("second")
            return {**state, "b": state["a"] + 1}

        manager.add("first", first)
        manager.add("second", second)
        result = await manager.run({})
        self.assertEqual(order, ["first", "second"])
        self.assertEqual(result["b"], 2)

    async def test_saga_compensates_in_reverse_order(self) -> None:
        saga = Saga()
        events: list[str] = []

        async def compensate_one():
            events.append("one")

        async def compensate_two():
            events.append("two")

        saga.add_compensation("one", compensate_one)
        saga.add_compensation("two", compensate_two)
        actions = await saga.compensate()
        self.assertEqual(actions, ["two", "one"])
        self.assertEqual(events, ["two", "one"])

    async def test_watcher_blocks_unauthorized_paths(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            watcher = AuthorizedWriteWatcher(root, ["allowed.txt"])
            self.assertEqual(watcher.validate_path("allowed.txt"), "allowed.txt")
            with self.assertRaises(SecurityViolation):
                watcher.validate_path("blocked.txt")

    async def test_action_cache_round_trip(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            frontend = FrontendIR(task_id="task", base_commit="abcdef1", authorized_files=["a.py"])
            cache = ActionCache(Path(tmp) / "cache.db")
            key = cache.put(frontend, "constitution", patch="diff --git a/a.py b/a.py", verification_summary={"ok": True})
            hit = cache.get_by_inputs(frontend, "constitution")
            self.assertIsNotNone(hit)
            assert hit is not None
            self.assertEqual(hit.action_key, key)
            self.assertEqual(hit.verification_summary["ok"], True)

    async def test_pipeline_executes_and_populates_cache(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            repo = self._init_repo(Path(tmp))
            self._write_pytest_test(
                repo,
                """
from sample_app import value

def test_bug():
    assert value() == 2
""".strip()
                + "\n",
            )
            base_commit = self._commit_all(repo, "initial")
            patch = """diff --git a/sample_app.py b/sample_app.py
index 1c02a8f..75db990 100644
--- a/sample_app.py
+++ b/sample_app.py
@@ -1,2 +1,2 @@
 def value():
-    return 1
+    return 2
"""
            executor = FakeExecutor(patch=patch, touched_files=["sample_app.py"])
            pipeline = Pipeline(
                executor=executor,
                action_cache=ActionCache(repo / "action_cache.db"),
                verifier=VerificationRunner(),
                event_store=EventStore(repo / "events.jsonl"),
            )
            request = PipelineRequest(
                task_id="bugfix",
                base_commit=base_commit,
                authorized_files=["sample_app.py"],
                constitution="Keep fix scoped",
                verification_contracts=[
                    {"kind": "fail_to_pass", "selectors": [{"selector": "test_app.py::test_bug"}]},
                    {"kind": "pass_to_pass", "selectors": [{"selector": "test_app.py::test_bug"}]},
                ],
                model_id="gpt-5.4",
                repo_root=str(repo),
                sandbox_type=SandboxType.LOCAL,
                resource_limits=ResourceLimits(max_runtime_seconds=60, max_memory_mb=256),
            )
            result = await pipeline.run(request)
            self.assertFalse(result.cache_hit)
            self.assertEqual(executor.calls, 1)
            self.assertIn("execution_completed", [event["event_type"] for event in result.events])

            cached = await pipeline.run(request)
            self.assertTrue(cached.cache_hit)
            self.assertEqual(executor.calls, 1)
            self.assertIn("cache_hit", [event["event_type"] for event in cached.events])

    async def test_pipeline_blocks_unauthorized_patch(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            repo = self._init_repo(Path(tmp))
            self._write_pytest_test(
                repo,
                """
from sample_app import value

def test_bug():
    assert value() == 2
""".strip()
                + "\n",
            )
            base_commit = self._commit_all(repo, "initial")
            patch = """diff --git a/other.py b/other.py
new file mode 100644
--- /dev/null
+++ b/other.py
@@ -0,0 +1 @@
+print("oops")
"""
            pipeline = Pipeline(
                executor=FakeExecutor(patch=patch, touched_files=["other.py"]),
                action_cache=ActionCache(repo / "action_cache.db"),
                verifier=VerificationRunner(),
                event_store=EventStore(repo / "events.jsonl"),
            )
            request = PipelineRequest(
                task_id="bugfix",
                base_commit=base_commit,
                authorized_files=["sample_app.py"],
                constitution="Keep fix scoped",
                verification_contracts=[
                    {"kind": "fail_to_pass", "selectors": [{"selector": "test_app.py::test_bug"}]},
                    {"kind": "pass_to_pass", "selectors": [{"selector": "test_app.py::test_bug"}]},
                ],
                model_id="gpt-5.4",
                repo_root=str(repo),
                sandbox_type=SandboxType.LOCAL,
            )
            with self.assertRaises(SecurityViolation):
                await pipeline.run(request)

    def _init_repo(self, root: Path) -> Path:
        subprocess.run(["git", "init"], cwd=root, check=True, capture_output=True, text=True)
        subprocess.run(["git", "config", "user.email", "test@example.com"], cwd=root, check=True)
        subprocess.run(["git", "config", "user.name", "Test User"], cwd=root, check=True)
        (root / "sample_app.py").write_text("def value():\n    return 1\n", encoding="utf-8")
        return root

    def _write_pytest_test(self, root: Path, content: str) -> None:
        (root / "test_app.py").write_text(content, encoding="utf-8")

    def _commit_all(self, root: Path, message: str) -> str:
        subprocess.run(["git", "add", "."], cwd=root, check=True)
        subprocess.run(["git", "commit", "-m", message], cwd=root, check=True, capture_output=True, text=True)
        return subprocess.run(
            ["git", "rev-parse", "HEAD"], cwd=root, check=True, capture_output=True, text=True
        ).stdout.strip()


if __name__ == "__main__":
    unittest.main()
