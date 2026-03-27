from __future__ import annotations

import subprocess
import tempfile
import unittest
from pathlib import Path

from core import StablePoint, VCSAdapter


class VCSAdapterTests(unittest.TestCase):
    def test_revert_to_stable_restores_base_commit(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            repo = Path(tmp)
            subprocess.run(["git", "init"], cwd=repo, check=True, capture_output=True, text=True)
            subprocess.run(["git", "config", "user.email", "test@example.com"], cwd=repo, check=True)
            subprocess.run(["git", "config", "user.name", "Test User"], cwd=repo, check=True)
            file_path = repo / "sample_app.py"
            file_path.write_text("def value():\n    return 1\n", encoding="utf-8")
            subprocess.run(["git", "add", "."], cwd=repo, check=True)
            subprocess.run(["git", "commit", "-m", "initial"], cwd=repo, check=True, capture_output=True, text=True)

            adapter = VCSAdapter()
            stable = adapter.snapshot_stable(repo)
            patch = """diff --git a/sample_app.py b/sample_app.py
index 1c02a8f..75db990 100644
--- a/sample_app.py
+++ b/sample_app.py
@@ -1,2 +1,2 @@
 def value():
-    return 1
+    return 2
"""
            adapter.apply_patch(repo, patch)
            self.assertIn("return 2", file_path.read_text(encoding="utf-8"))
            adapter.revert_to_stable(stable)
            self.assertIn("return 1", file_path.read_text(encoding="utf-8"))
            head = subprocess.run(["git", "rev-parse", "HEAD"], cwd=repo, check=True, capture_output=True, text=True).stdout.strip()
            self.assertEqual(head, stable.commit)


if __name__ == "__main__":
    unittest.main()
