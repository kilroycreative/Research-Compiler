from __future__ import annotations

import asyncio
import tempfile
import unittest
from pathlib import Path

from core import RefinementQueueRunner


class RefinementRunnerTests(unittest.TestCase):
    def test_refinement_queue_runner_marks_ticket_done(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            queue_root = Path(tmp)
            tickets_dir = queue_root / ".codex-autorunner" / "tickets"
            tickets_dir.mkdir(parents=True, exist_ok=True)
            ticket = tickets_dir / "RTICKET-001.md"
            ticket.write_text(
                "---\n"
                'title: "Fix thing"\n'
                'agent: "codex"\n'
                "done: false\n"
                'ticket_id: "rticket-001"\n'
                "---\n",
                encoding="utf-8",
            )
            runner = RefinementQueueRunner(queue_root)
            results = asyncio.run(runner.run_command("python3 -c \"print('ok')\""))
            self.assertEqual(results[0]["status"], "ok")
            self.assertIn("done: true", ticket.read_text(encoding="utf-8"))


if __name__ == "__main__":
    unittest.main()
