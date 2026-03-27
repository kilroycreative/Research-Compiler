from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path

from core import RefinementEmitter, RefinementPlanner


class RefinementPlannerTests(unittest.TestCase):
    def test_planner_builds_refinement_tasks_from_failed_summary(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            repo = Path(tmp)
            summary_dir = repo / ".pipeline" / "task-a"
            summary_dir.mkdir(parents=True, exist_ok=True)
            summary = {
                "task_id": "task-a",
                "status": "failed",
                "cache_hit": False,
                "workspace": str(repo),
                "touched_files": [],
                "verification": {},
                "duration_seconds": 0.123,
                "dispatch_attempts": [],
                "total_cost_usd": 0.02,
                "diagnostics": [
                    {
                        "level": "error",
                        "code": "SECURITY_VIOLATION",
                        "message": "Attempted write outside authorized files.",
                        "pass_name": "execute_or_replay",
                        "file_path": "CLAUDE.md",
                    }
                ],
                "error": "Attempted write outside authorized files.",
            }
            (summary_dir / "summary.json").write_text(json.dumps(summary), encoding="utf-8")

            tasks = RefinementPlanner(repo).plan()
            self.assertEqual(len(tasks), 1)
            task = tasks[0]
            self.assertEqual(task.source_task_id, "task-a")
            self.assertEqual(task.priority, "critical")
            self.assertIn("Security Violation", task.title)

    def test_emitter_writes_manifest_and_markdown(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            repo = Path(tmp)
            summary_dir = repo / ".pipeline" / "task-b"
            summary_dir.mkdir(parents=True, exist_ok=True)
            (summary_dir / "summary.json").write_text(
                json.dumps(
                    {
                        "task_id": "task-b",
                        "status": "failed",
                        "diagnostics": [],
                        "dispatch_attempts": [],
                        "error": "Verifier failed",
                    }
                ),
                encoding="utf-8",
            )
            tasks = RefinementPlanner(repo).plan()
            output_dir = repo / ".pipeline" / "refinements"
            manifest = RefinementEmitter(output_dir).write(tasks)
            self.assertTrue(manifest.exists())
            ticket_files = list(output_dir.glob("refine-*.md"))
            self.assertEqual(len(ticket_files), 1)


if __name__ == "__main__":
    unittest.main()
