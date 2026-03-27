from __future__ import annotations

import json
import subprocess
import tempfile
import unittest
from pathlib import Path


class HumanLayerTicketToolTests(unittest.TestCase):
    def test_launch_ticket_tool_creates_worktree_without_launch(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            repo = Path(tmp) / "repo"
            repo.mkdir(parents=True, exist_ok=True)
            subprocess.run(["git", "init"], cwd=repo, check=True, capture_output=True, text=True)
            subprocess.run(["git", "config", "user.email", "test@example.com"], cwd=repo, check=True)
            subprocess.run(["git", "config", "user.name", "Test User"], cwd=repo, check=True)
            (repo / "README.md").write_text("hello\n", encoding="utf-8")
            subprocess.run(["git", "add", "."], cwd=repo, check=True)
            subprocess.run(["git", "commit", "-m", "initial"], cwd=repo, check=True, capture_output=True, text=True)

            ticket = Path(tmp) / "TICKET-001.md"
            ticket.write_text(
                "---\n"
                'title: "Example Ticket"\n'
                'agent: "codex"\n'
                "done: false\n"
                'ticket_id: "ticket-001"\n'
                "---\n\n"
                "## Files\n"
                "- `README.md`\n",
                encoding="utf-8",
            )
            process = subprocess.run(
                [
                    "python3",
                    "tools/launch_humanlayer_ticket.py",
                    "--ticket",
                    str(ticket),
                    "--repo-root",
                    str(repo),
                    "--no-launch",
                ],
                cwd=Path(__file__).resolve().parents[1],
                text=True,
                capture_output=True,
                check=False,
            )
            self.assertEqual(process.returncode, 0, process.stderr)
            payload = json.loads(process.stdout)
            self.assertIn("/.deep-loop/worktrees/ticket-001-", payload["workspace"])


if __name__ == "__main__":
    unittest.main()
