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
    ModelTier,
    PassManager,
    Pipeline,
    PipelineFailure,
    PipelineRequest,
    ResourceConstraints,
    ResourceLimits,
    Saga,
    SandboxType,
    SecurityViolation,
    TieredDispatcher,
    VerificationFailure,
    VerificationRunner,
)
from core.adapters.base import RuntimeEvent, RuntimeSession
from core.adapters.local import LocalRuntimeAdapter
from core.adapters.remote_compute import GenericRemoteRuntimeAdapter, RemoteSandboxHandle, RemoteSandboxProvider
from core.worktree import WorktreeManager
from core.pipeline import ExecutionResult
from core.verifier import CommandResult
from core.ir import ExecutionPlan


class FakeExecutor:
    def __init__(self, patch: str, touched_files: list[str], metadata: dict | None = None) -> None:
        self.patch = patch
        self.touched_files = touched_files
        self.metadata = metadata or {}
        self.calls = 0

    async def execute(self, plan, workspace):
        self.calls += 1
        return ExecutionResult(patch=self.patch, touched_files=self.touched_files, metadata=self.metadata)


class SlowExecutor(FakeExecutor):
    async def execute(self, plan, workspace):
        self.calls += 1
        await asyncio.sleep(0.2)
        return ExecutionResult(patch=self.patch, touched_files=self.touched_files, metadata=self.metadata)


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


class StreamingLocalAdapter(LocalRuntimeAdapter):
    def __init__(self, repo_root: Path, events: list[RuntimeEvent], worktree_manager: WorktreeManager | None = None) -> None:
        super().__init__(repo_root, worktree_manager=worktree_manager)
        self._events = events

    async def stream_events(self, session: RuntimeSession):
        for event in self._events:
            yield event
            await asyncio.sleep(0)


class FixedPatchExecutor:
    def __init__(self, patch: str, *, prompt_tokens: int = 100, completion_tokens: int = 100) -> None:
        self.patch = patch
        self.prompt_tokens = prompt_tokens
        self.completion_tokens = completion_tokens

    async def execute(self, plan, workspace):
        del plan, workspace
        return ExecutionResult(
            patch=self.patch,
            touched_files=["sample_app.py"] if self.patch else [],
            metadata={"prompt_tokens": self.prompt_tokens, "completion_tokens": self.completion_tokens},
        )


class PipelineRemoteProvider(RemoteSandboxProvider):
    name = "pipeline-remote"

    def __init__(self) -> None:
        self.pytest_calls = 0
        self.remote_file = "def value():\n    return 2\n"

    async def create(self, *, plan: ExecutionPlan) -> RemoteSandboxHandle:
        return RemoteSandboxHandle(provider=self.name, sandbox_id="sandbox-1", remote_root="/workspace")

    async def destroy(self, handle: RemoteSandboxHandle) -> None:
        del handle

    async def run_command(self, handle: RemoteSandboxHandle, command: list[str], cwd: str) -> CommandResult:
        del handle, cwd
        joined = " ".join(command)
        if "pytest" in joined:
            self.pytest_calls += 1
            exit_code = 1 if self.pytest_calls == 1 else 0
            return CommandResult(command=command, exit_code=exit_code, stdout="", stderr="")
        if "base64.b64encode" in joined:
            import base64

            return CommandResult(
                command=command,
                exit_code=0,
                stdout=base64.b64encode(self.remote_file.encode("utf-8")).decode("ascii"),
                stderr="",
            )
        return CommandResult(command=command, exit_code=0, stdout="", stderr="")


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

    async def test_pipeline_kills_on_live_unauthorized_runtime_event(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            repo = self._init_repo(Path(tmp))
            self._write_pytest_test(
                repo,
                """
from sample_app import value

def test_bug():
    assert value() == 1
""".strip()
                + "\n",
            )
            base_commit = self._commit_all(repo, "initial")
            worktree_manager = FakeWorktreeManager(repo)
            runtime_adapter = StreamingLocalAdapter(
                repo,
                events=[RuntimeEvent(path="CLAUDE.md", action="modified")],
                worktree_manager=worktree_manager,
            )
            pipeline = Pipeline(
                executor=SlowExecutor(patch="", touched_files=[]),
                action_cache=ActionCache(repo / "action_cache.db"),
                verifier=VerificationRunner(),
                event_store=EventStore(repo / "events.jsonl"),
                runtime_adapter=runtime_adapter,
                worktree_manager=worktree_manager,
            )
            request = PipelineRequest(
                task_id="bugfix",
                base_commit=base_commit,
                authorized_files=["sample_app.py"],
                constitution="Keep fix scoped",
                verification_contracts=[
                    {"kind": "pass_to_pass", "selectors": [{"selector": "test_app.py::test_bug"}]},
                ],
                model_id="gpt-5.4",
                repo_root=str(repo),
                sandbox_type=SandboxType.WORKTREE,
            )
            with self.assertRaises(SecurityViolation):
                await pipeline.run(request)
            events = EventStore(repo / "events.jsonl").read_all()
            self.assertIn("runtime_event", [event["event_type"] for event in events])
            self.assertIn(repo / "bugfix-workspace", worktree_manager.cleaned)

    async def test_pipeline_escalates_from_draft_to_production(self) -> None:
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
            bad_patch = """diff --git a/sample_app.py b/sample_app.py
index 1c02a8f..75db990 100644
--- a/sample_app.py
+++ b/sample_app.py
@@ -1,2 +1,2 @@
 def value():
-    return 1
+    return 3
"""
            good_patch = """diff --git a/sample_app.py b/sample_app.py
index 1c02a8f..75db990 100644
--- a/sample_app.py
+++ b/sample_app.py
@@ -1,2 +1,2 @@
 def value():
-    return 1
+    return 2
"""
            dispatcher = TieredDispatcher(
                draft_executor=FixedPatchExecutor(bad_patch, prompt_tokens=100, completion_tokens=50),
                production_executor=FixedPatchExecutor(good_patch, prompt_tokens=200, completion_tokens=80),
                draft_model="gpt-4o-mini",
                production_model="gpt-5",
            )
            pipeline = Pipeline(
                executor=dispatcher,
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
                model_id="gpt-5",
                repo_root=str(repo),
                sandbox_type=SandboxType.LOCAL,
                resource_limits=ResourceLimits(max_runtime_seconds=60, max_memory_mb=256),
                resource_constraints=ResourceConstraints(model_tier=ModelTier.DRAFT, max_cost_usd=5.0, allow_escalation=True),
            )
            result = await pipeline.run(request)
            self.assertFalse(result.cache_hit)
            events = EventStore(repo / "events.jsonl").read_all()
            attempts = [event for event in events if event["event_type"] == "dispatch_attempt"]
            self.assertEqual(len(attempts), 2)
            self.assertEqual(attempts[0]["payload"]["status"], "verification_failed")
            self.assertEqual(attempts[1]["payload"]["status"], "verified")

    async def test_pipeline_reverts_to_stable_on_verification_failure(self) -> None:
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
            bad_patch = """diff --git a/sample_app.py b/sample_app.py
index 1c02a8f..75db990 100644
--- a/sample_app.py
+++ b/sample_app.py
@@ -1,2 +1,2 @@
 def value():
-    return 1
+    return 3
"""
            pipeline = Pipeline(
                executor=FixedPatchExecutor(bad_patch, prompt_tokens=100, completion_tokens=50),
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
                model_id="gpt-5",
                repo_root=str(repo),
                sandbox_type=SandboxType.LOCAL,
                resource_limits=ResourceLimits(max_runtime_seconds=60, max_memory_mb=256),
                resource_constraints=ResourceConstraints(model_tier=ModelTier.PRODUCTION, allow_escalation=False),
            )
            with self.assertRaises(VerificationFailure):
                await pipeline.run(request)
            current = (repo / "sample_app.py").read_text(encoding="utf-8")
            self.assertIn("return 1", current)
            head = subprocess.run(["git", "rev-parse", "HEAD"], cwd=repo, check=True, capture_output=True, text=True).stdout.strip()
            self.assertEqual(head, base_commit)

    async def test_pipeline_verifies_remote_before_local_reconciliation(self) -> None:
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
            provider = PipelineRemoteProvider()
            runtime_adapter = GenericRemoteRuntimeAdapter(
                repo,
                provider=provider,
                worktree_manager=FakeWorktreeManager(repo),
            )
            patch = """diff --git a/sample_app.py b/sample_app.py
index 1c02a8f..75db990 100644
--- a/sample_app.py
+++ b/sample_app.py
@@ -1,2 +1,2 @@
 def value():
-    return 1
+    return 2
"""
            pipeline = Pipeline(
                executor=FakeExecutor(patch=patch, touched_files=["sample_app.py"]),
                action_cache=ActionCache(repo / "action_cache.db"),
                verifier=VerificationRunner(),
                event_store=EventStore(repo / "events.jsonl"),
                runtime_adapter=runtime_adapter,
            )
            request = PipelineRequest(
                task_id="remote-bugfix",
                base_commit=base_commit,
                authorized_files=["sample_app.py"],
                constitution="Keep fix scoped",
                verification_contracts=[
                    {"kind": "fail_to_pass", "selectors": [{"selector": "test_app.py::test_bug"}]},
                    {"kind": "pass_to_pass", "selectors": [{"selector": "test_app.py::test_bug"}]},
                ],
                model_id="gpt-5.4",
                repo_root=str(repo),
                sandbox_type=SandboxType.E2B,
            )
            result = await pipeline.run(request)
            self.assertFalse(result.cache_hit)
            self.assertEqual(provider.pytest_calls, 2)
            current = (repo / "remote-bugfix-workspace" / "sample_app.py").read_text(encoding="utf-8")
            self.assertIn("return 2", current)

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
