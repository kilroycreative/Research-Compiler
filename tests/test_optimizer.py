from __future__ import annotations

import asyncio
import subprocess
import tempfile
import unittest
from pathlib import Path

from core import (
    ActionCache,
    ContextPruner,
    EventStore,
    Linker,
    OptimizerCache,
    Pipeline,
    PipelineRequest,
    ResourceLimits,
    SandboxType,
    SymbolTableBuilder,
    VerificationRunner,
)
from core.pipeline import ExecutionResult


class NoopExecutor:
    async def execute(self, plan, workspace):
        del workspace
        return ExecutionResult(patch="", touched_files=[], metadata={"symbol_count": len(plan.symbol_table)})


class CountingSymbolTableBuilder(SymbolTableBuilder):
    def __init__(self) -> None:
        self.calls = 0

    def build(self, repo_root, file_paths):
        self.calls += 1
        return super().build(repo_root, file_paths)


class OptimizerTests(unittest.TestCase):
    def test_symbol_table_and_linker(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / "helpers.py").write_text("def helper(x):\n    return x + 1\n", encoding="utf-8")
            (root / "sample_app.py").write_text(
                "from helpers import helper\n\nVALUE = 1\n\ndef value():\n    return helper(VALUE)\n",
                encoding="utf-8",
            )
            builder = SymbolTableBuilder()
            symbols = builder.build(root, ["helpers.py", "sample_app.py"])
            self.assertTrue(any(symbol.name == "helper" for symbol in symbols))
            self.assertTrue(any(symbol.name == "value" for symbol in symbols))

            linker = Linker()
            links = linker.build(root, ["sample_app.py"], symbols)
            self.assertTrue(any(link.symbol_name == "helper" and link.resolved_file_path == "helpers.py" for link in links))

            pruner = ContextPruner()
            slices = pruner.build(root, ["sample_app.py"], symbols, links)
            self.assertEqual(len(slices), 1)
            self.assertIn("def value", slices[0].excerpt)
            self.assertIn("helper", slices[0].rationale)

    def test_pipeline_populates_optimized_middle_end(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            repo = Path(tmp)
            subprocess.run(["git", "init"], cwd=repo, check=True, capture_output=True, text=True)
            subprocess.run(["git", "config", "user.email", "test@example.com"], cwd=repo, check=True)
            subprocess.run(["git", "config", "user.name", "Test User"], cwd=repo, check=True)
            (repo / "sample_app.py").write_text("def value():\n    return 1\n", encoding="utf-8")
            (repo / "test_app.py").write_text("from sample_app import value\n\ndef test_bug():\n    assert value() == 1\n", encoding="utf-8")
            subprocess.run(["git", "add", "."], cwd=repo, check=True)
            subprocess.run(["git", "commit", "-m", "initial"], cwd=repo, check=True, capture_output=True, text=True)
            base_commit = subprocess.run(
                ["git", "rev-parse", "HEAD"], cwd=repo, check=True, capture_output=True, text=True
            ).stdout.strip()

            pipeline = Pipeline(
                executor=NoopExecutor(),
                action_cache=ActionCache(repo / "action_cache.db"),
                verifier=VerificationRunner(),
                event_store=EventStore(repo / "events.jsonl"),
            )
            request = PipelineRequest(
                task_id="optimize",
                base_commit=base_commit,
                authorized_files=["sample_app.py"],
                constitution="Stay scoped",
                verification_contracts=[{"kind": "pass_to_pass", "selectors": [{"selector": "test_app.py::test_bug"}]}],
                model_id="gpt-5",
                repo_root=str(repo),
                sandbox_type=SandboxType.LOCAL,
                resource_limits=ResourceLimits(max_runtime_seconds=30, max_memory_mb=128),
            )
            result = asyncio.run(pipeline.run(request))
            self.assertGreaterEqual(len(result.middle_end_ir.symbol_table), 1)
            self.assertEqual(len(result.middle_end_ir.context_slices), 1)
            self.assertIn("context_optimized", [event["event_type"] for event in result.events])

    def test_optimizer_cache_skips_rebuild_on_unchanged_input(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            repo = Path(tmp)
            subprocess.run(["git", "init"], cwd=repo, check=True, capture_output=True, text=True)
            subprocess.run(["git", "config", "user.email", "test@example.com"], cwd=repo, check=True)
            subprocess.run(["git", "config", "user.name", "Test User"], cwd=repo, check=True)
            (repo / "sample_app.py").write_text("def value():\n    return 1\n", encoding="utf-8")
            (repo / "test_app.py").write_text("from sample_app import value\n\ndef test_bug():\n    assert value() == 1\n", encoding="utf-8")
            subprocess.run(["git", "add", "."], cwd=repo, check=True)
            subprocess.run(["git", "commit", "-m", "initial"], cwd=repo, check=True, capture_output=True, text=True)
            base_commit = subprocess.run(
                ["git", "rev-parse", "HEAD"], cwd=repo, check=True, capture_output=True, text=True
            ).stdout.strip()

            builder = CountingSymbolTableBuilder()
            pipeline = Pipeline(
                executor=NoopExecutor(),
                action_cache=ActionCache(repo / "action_cache.db"),
                verifier=VerificationRunner(),
                event_store=EventStore(repo / "events.jsonl"),
                optimizer_cache=OptimizerCache(repo / "optimizer_cache.db"),
                symbol_table_builder=builder,
            )
            request = PipelineRequest(
                task_id="optimize",
                base_commit=base_commit,
                authorized_files=["sample_app.py"],
                constitution="Stay scoped",
                verification_contracts=[{"kind": "pass_to_pass", "selectors": [{"selector": "test_app.py::test_bug"}]}],
                model_id="gpt-5",
                repo_root=str(repo),
                sandbox_type=SandboxType.LOCAL,
                resource_limits=ResourceLimits(max_runtime_seconds=30, max_memory_mb=128),
            )
            asyncio.run(pipeline.run(request))
            asyncio.run(pipeline.run(request))
            self.assertEqual(builder.calls, 1)


if __name__ == "__main__":
    unittest.main()
