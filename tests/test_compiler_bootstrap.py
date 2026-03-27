from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path

from tools.compiler_bootstrap import generate


class CompilerBootstrapTests(unittest.TestCase):
    def test_generate_writes_humanlayer_launchers(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            config = {
                "project_name": "Test Project",
                "product_summary": "summary",
                "repo": "./app",
                "debt": {
                    "work_items": [
                        {
                            "id": "DEBT-001",
                            "title": "Task",
                            "primitive": "x",
                            "package": "core",
                            "scope": ["do task"],
                            "acceptance": ["works"],
                            "ground_truth": ["truth"],
                            "files": ["README.md"],
                        }
                    ],
                    "execution_order": [["DEBT-001"]],
                },
                "review": {"gates": []},
                "factory": {"project": "test-project", "risk_classification": {"DEBT-001": "medium"}},
            }
            config_path = root / "lowering_config.json"
            config_path.write_text(json.dumps(config), encoding="utf-8")
            factory_dir = root / "factory"
            generate(config_path, factory_dir)
            self.assertTrue((factory_dir / "launch-humanlayer-ticket.sh").exists())
            self.assertTrue((factory_dir / "launch-humanlayer-refinement.sh").exists())


if __name__ == "__main__":
    unittest.main()
