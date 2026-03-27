from __future__ import annotations

import asyncio
import tempfile
import unittest
from pathlib import Path

from core import MergeQueue, PipelineRequest, QueueTask, ResourceLimits, SandboxType


class FakePipeline:
    def __init__(self, recorder: list[tuple[str, str]]) -> None:
        self.recorder = recorder
        self.active = 0
        self.max_active = 0

    async def run(self, request: PipelineRequest):
        self.active += 1
        self.max_active = max(self.max_active, self.active)
        self.recorder.append((request.task_id, "start"))
        await asyncio.sleep(0.1)
        self.recorder.append((request.task_id, "end"))
        self.active -= 1
        return type("Result", (), {"workspace": request.repo_root})


class MergeQueueTests(unittest.IsolatedAsyncioTestCase):
    async def test_merge_queue_serializes_overlapping_files(self) -> None:
        recorder: list[tuple[str, str]] = []
        pipeline = FakePipeline(recorder)
        queue = MergeQueue(pipeline_factory=lambda: pipeline, max_parallel=2)
        with tempfile.TemporaryDirectory() as tmp:
            request_a = self._request(Path(tmp), "a", ["same.py"])
            request_b = self._request(Path(tmp), "b", ["same.py"])
            results = await queue.run([QueueTask("a", request_a), QueueTask("b", request_b)])
            self.assertTrue(all(item.status == "ok" for item in results))
            self.assertEqual(recorder, [("a", "start"), ("a", "end"), ("b", "start"), ("b", "end")])

    async def test_merge_queue_allows_parallel_non_overlapping_files(self) -> None:
        recorder: list[tuple[str, str]] = []
        pipelines: list[FakePipeline] = []

        def factory():
            pipeline = FakePipeline(recorder)
            pipelines.append(pipeline)
            return pipeline

        queue = MergeQueue(pipeline_factory=factory, max_parallel=2)
        with tempfile.TemporaryDirectory() as tmp:
            request_a = self._request(Path(tmp), "a", ["a.py"])
            request_b = self._request(Path(tmp), "b", ["b.py"])
            results = await queue.run([QueueTask("a", request_a), QueueTask("b", request_b)])
            self.assertTrue(all(item.status == "ok" for item in results))
            self.assertEqual({event for _, event in recorder}, {"start", "end"})
            self.assertEqual(len([item for item in recorder if item[1] == "start"]), 2)

    def _request(self, root: Path, task_id: str, files: list[str]) -> PipelineRequest:
        return PipelineRequest(
            task_id=task_id,
            base_commit="abcdef1",
            authorized_files=files,
            constitution="Scoped",
            verification_contracts=[{"kind": "pass_to_pass", "selectors": [{"selector": "tests"}]}],
            model_id="gpt-5",
            repo_root=str(root),
            sandbox_type=SandboxType.LOCAL,
            resource_limits=ResourceLimits(max_runtime_seconds=30, max_memory_mb=128),
        )


if __name__ == "__main__":
    unittest.main()
