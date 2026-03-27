from __future__ import annotations

import asyncio
import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import MagicMock, patch

from core import BudgetExceeded, ModelTier, ResourceConstraints, TieredDispatcher
from core.executors import (
    ExecutorConfig,
    ModelExecutionError,
    ModelProvider,
    OpenAICompatibleExecutor,
    build_executor,
    extract_patch_paths,
    extract_unified_diff,
)
from core.ir import ExecutionPlan, ResourceLimits, SandboxType


class FixedResultExecutor:
    def __init__(self, patch: str, *, prompt_tokens: int, completion_tokens: int) -> None:
        self.patch = patch
        self.prompt_tokens = prompt_tokens
        self.completion_tokens = completion_tokens

    async def execute(self, plan: ExecutionPlan, workspace: Path):
        del plan, workspace
        from core.execution_types import ExecutionResult

        return ExecutionResult(
            patch=self.patch,
            touched_files=["a.py"] if self.patch else [],
            metadata={"prompt_tokens": self.prompt_tokens, "completion_tokens": self.completion_tokens},
        )


class ExecutorTests(unittest.TestCase):
    def test_extract_unified_diff_from_fenced_output(self) -> None:
        text = "```diff\ndiff --git a/a.py b/a.py\n--- a/a.py\n+++ b/a.py\n@@ -1 +1 @@\n-print(1)\n+print(2)\n```"
        self.assertTrue(extract_unified_diff(text).startswith("diff --git"))

    def test_extract_patch_paths(self) -> None:
        patch = "diff --git a/a.py b/a.py\n--- a/a.py\n+++ b/a.py\n"
        self.assertEqual(extract_patch_paths(patch), ["a.py"])

    def test_build_executor_for_claude(self) -> None:
        executor = build_executor(ExecutorConfig(provider=ModelProvider.CLAUDE_CODE, model="sonnet"))
        self.assertEqual(executor.config.provider, ModelProvider.CLAUDE_CODE)

    @patch("core.executors.request.urlopen")
    def test_openai_compatible_executor_parses_output(self, mock_urlopen: MagicMock) -> None:
        response = MagicMock()
        response.read.return_value = json.dumps(
            {
                "output": [
                    {
                        "content": [
                            {
                                "type": "output_text",
                                "text": "diff --git a/a.py b/a.py\n--- a/a.py\n+++ b/a.py\n@@ -1 +1 @@\n-print(1)\n+print(2)\n",
                            }
                        ]
                    }
                ]
            }
        ).encode("utf-8")
        mock_urlopen.return_value.__enter__.return_value = response

        executor = OpenAICompatibleExecutor(
            ExecutorConfig(provider=ModelProvider.LM_STUDIO, model="local-model"),
            default_base_url="http://localhost:1234/v1",
            default_api_key_env="LM_STUDIO_API_KEY",
        )
        with tempfile.TemporaryDirectory() as tmp:
            workspace = Path(tmp)
            (workspace / "a.py").write_text("print(1)\n", encoding="utf-8")
            plan = ExecutionPlan(
                task_id="task",
                base_commit="abcdef1",
                authorized_files=["a.py"],
                constitution="Stay scoped",
                verification_contracts=[{"kind": "pass_to_pass", "selectors": [{"selector": "tests"}]}],
                model_id="local-model",
                sandbox_type=SandboxType.LOCAL,
                resource_limits=ResourceLimits(max_runtime_seconds=60, max_memory_mb=256),
            )
            result = asyncio.run(executor.execute(plan, workspace))
        self.assertEqual(result.touched_files, ["a.py"])

    def test_extract_unified_diff_raises_for_non_diff(self) -> None:
        with self.assertRaises(ModelExecutionError):
            extract_unified_diff("hello")

    def test_dispatcher_enforces_cost_budget(self) -> None:
        dispatcher = TieredDispatcher(
            draft_executor=FixedResultExecutor("", prompt_tokens=1000, completion_tokens=1000),
            production_executor=FixedResultExecutor("", prompt_tokens=500_000, completion_tokens=500_000),
            draft_model="gpt-4o-mini",
            production_model="gpt-5",
        )
        plan = ExecutionPlan(
            task_id="task",
            base_commit="abcdef1",
            authorized_files=["a.py"],
            constitution="Stay scoped",
            verification_contracts=[{"kind": "pass_to_pass", "selectors": [{"selector": "tests"}]}],
            model_id="gpt-5",
            sandbox_type=SandboxType.LOCAL,
            resource_limits=ResourceLimits(max_runtime_seconds=60, max_memory_mb=256),
            resource_constraints=ResourceConstraints(model_tier=ModelTier.PRODUCTION, max_cost_usd=0.01),
        )
        with tempfile.TemporaryDirectory() as tmp, self.assertRaises(BudgetExceeded):
            asyncio.run(dispatcher.execute(plan, Path(tmp)))


if __name__ == "__main__":
    unittest.main()
