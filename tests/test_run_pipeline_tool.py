from __future__ import annotations

import json
import subprocess
import tempfile
import unittest
from pathlib import Path


class RunPipelineToolTests(unittest.TestCase):
    def test_tool_emits_refinement_artifacts_on_success(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            repo = self._init_repo(Path(tmp))
            self._write_test(repo)
            base_commit = self._commit_all(repo)
            (repo / ".pipeline").mkdir(parents=True, exist_ok=True)
            (repo / ".pipeline" / "task.patch").write_text(
                """diff --git a/sample_app.py b/sample_app.py
index 1c02a8f..75db990 100644
--- a/sample_app.py
+++ b/sample_app.py
@@ -1,2 +1,2 @@
 def value():
-    return 1
+    return 2
""",
                encoding="utf-8",
            )
            request = {
                "task_id": "task",
                "base_commit": base_commit,
                "authorized_files": ["sample_app.py"],
                "constitution": "Keep fix scoped",
                "verification_contracts": [
                    {"kind": "fail_to_pass", "selectors": [{"selector": "test_app.py::test_bug"}]},
                    {"kind": "pass_to_pass", "selectors": [{"selector": "test_app.py::test_bug"}]},
                ],
                "model_id": "gpt-5",
                "repo_root": str(repo),
                "sandbox_type": "local",
            }
            request_path = repo / "request.json"
            request_path.write_text(json.dumps(request), encoding="utf-8")
            process = subprocess.run(
                ["python3", "tools/run_pipeline.py", "--request", str(request_path), "--cache-db", str(repo / "action_cache.db"), "--events", str(repo / "events.jsonl")],
                cwd=Path(__file__).resolve().parents[1],
                text=True,
                capture_output=True,
                check=False,
            )
            self.assertEqual(process.returncode, 0, process.stderr)
            payload = json.loads(process.stdout)
            self.assertTrue(payload["ok"])
            self.assertEqual(payload["refinements"]["count"], 0)
            self.assertTrue((repo / ".pipeline" / "refinement-queue" / "queue-manifest.json").exists())

    def test_tool_emits_refinement_artifacts_on_failure(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            repo = self._init_repo(Path(tmp))
            self._write_test(repo)
            base_commit = self._commit_all(repo)
            request = {
                "task_id": "task",
                "base_commit": base_commit,
                "authorized_files": ["sample_app.py"],
                "constitution": "Keep fix scoped",
                "verification_contracts": [
                    {"kind": "fail_to_pass", "selectors": [{"selector": "test_app.py::test_bug"}]},
                    {"kind": "pass_to_pass", "selectors": [{"selector": "test_app.py::test_bug"}]},
                ],
                "model_id": "gpt-5",
                "repo_root": str(repo),
                "sandbox_type": "local",
            }
            request_path = repo / "request.json"
            request_path.write_text(json.dumps(request), encoding="utf-8")
            process = subprocess.run(
                ["python3", "tools/run_pipeline.py", "--request", str(request_path), "--cache-db", str(repo / "action_cache.db"), "--events", str(repo / "events.jsonl")],
                cwd=Path(__file__).resolve().parents[1],
                text=True,
                capture_output=True,
                check=False,
            )
            self.assertNotEqual(process.returncode, 0)
            payload = json.loads(process.stdout)
            self.assertFalse(payload["ok"])
            self.assertGreaterEqual(payload["refinements"]["count"], 1)
            self.assertTrue((repo / ".pipeline" / "refinement-queue" / ".codex-autorunner" / "tickets" / "RTICKET-001.md").exists())

    def _init_repo(self, root: Path) -> Path:
        subprocess.run(["git", "init"], cwd=root, check=True, capture_output=True, text=True)
        subprocess.run(["git", "config", "user.email", "test@example.com"], cwd=root, check=True)
        subprocess.run(["git", "config", "user.name", "Test User"], cwd=root, check=True)
        (root / "sample_app.py").write_text("def value():\n    return 1\n", encoding="utf-8")
        return root

    def _write_test(self, root: Path) -> None:
        (root / "test_app.py").write_text(
            "from sample_app import value\n\ndef test_bug():\n    assert value() == 2\n",
            encoding="utf-8",
        )

    def _commit_all(self, root: Path) -> str:
        subprocess.run(["git", "add", "."], cwd=root, check=True)
        subprocess.run(["git", "commit", "-m", "initial"], cwd=root, check=True, capture_output=True, text=True)
        return subprocess.run(["git", "rev-parse", "HEAD"], cwd=root, check=True, capture_output=True, text=True).stdout.strip()


if __name__ == "__main__":
    unittest.main()
