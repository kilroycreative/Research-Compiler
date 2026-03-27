from __future__ import annotations

import json
import subprocess
import tempfile
import unittest
from pathlib import Path


class RefinementPromotionTests(unittest.TestCase):
    def test_promote_refinement_queue_into_factory(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            source_queue = root / ".pipeline" / "refinement-queue"
            tickets_dir = source_queue / ".codex-autorunner" / "tickets"
            tickets_dir.mkdir(parents=True, exist_ok=True)
            (tickets_dir / "AGENTS.md").write_text("# Refinements\n", encoding="utf-8")
            (tickets_dir / "RTICKET-001.md").write_text("# Ticket\n", encoding="utf-8")
            (source_queue / "queue-manifest.json").write_text(
                json.dumps({"tickets": [{"ticket_file": "RTICKET-001.md", "source_task_id": "task"}]}),
                encoding="utf-8",
            )
            factory_dir = root / "factory"
            process = subprocess.run(
                [
                    "python3",
                    "tools/promote_refinement_queue.py",
                    "--source-queue",
                    str(source_queue),
                    "--factory-dir",
                    str(factory_dir),
                ],
                cwd=Path(__file__).resolve().parents[1],
                text=True,
                capture_output=True,
                check=False,
            )
            self.assertEqual(process.returncode, 0, process.stderr)
            promoted = factory_dir / "refinement-queue"
            self.assertTrue((promoted / ".codex-autorunner" / "tickets" / "RTICKET-001.md").exists())
            self.assertTrue((promoted / "README.md").exists())
            payload = json.loads((promoted / "queue-manifest.json").read_text(encoding="utf-8"))
            self.assertIn("promoted_from", payload)


if __name__ == "__main__":
    unittest.main()
