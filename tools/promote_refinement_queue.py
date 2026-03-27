#!/usr/bin/env python3
"""Promote generated refinement tickets into the factory surface."""

from __future__ import annotations

import argparse
import json
import shutil
import stat
import textwrap
from pathlib import Path


def write_file(path: Path, content: str, executable: bool = False) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content, encoding="utf-8")
    if executable:
        path.chmod(path.stat().st_mode | stat.S_IXUSR)


def render_readme() -> str:
    return textwrap.dedent(
        """
        # Refinement Queue

        This folder contains compiler-generated follow-up tickets derived from pipeline failures and diagnostics.

        Contents:
        - `.codex-autorunner/tickets/` — ordered refinement tickets
        - `queue-manifest.json` — machine-readable mapping from source tasks to refinement tickets
        - `install-into-repo.sh` — stages the refinement queue into the target repo

        This queue is additive. It does not replace the primary compiler queue.
        """
    ).strip() + "\n"


def render_install_script() -> str:
    return textwrap.dedent(
        """
        #!/usr/bin/env bash
        set -euo pipefail

        ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd -P)"
        TARGET="${1:-$(pwd)}"

        mkdir -p "$TARGET/.codex-autorunner"
        rm -rf "$TARGET/.codex-autorunner/refinement-tickets"
        cp -R "$ROOT/.codex-autorunner/tickets" "$TARGET/.codex-autorunner/refinement-tickets"

        echo "Installed refinement queue into $TARGET/.codex-autorunner/refinement-tickets"
        """
    ).strip() + "\n"


def promote(source_queue: Path, factory_dir: Path) -> Path:
    source_queue = source_queue.resolve()
    factory_dir = factory_dir.resolve()
    if not source_queue.exists():
        raise FileNotFoundError(f"refinement queue not found: {source_queue}")

    target = factory_dir / "refinement-queue"
    shutil.rmtree(target, ignore_errors=True)
    shutil.copytree(source_queue, target)
    write_file(target / "README.md", render_readme())
    write_file(target / "install-into-repo.sh", render_install_script(), executable=True)

    manifest_path = target / "queue-manifest.json"
    if manifest_path.exists():
        payload = json.loads(manifest_path.read_text(encoding="utf-8"))
        payload["promoted_from"] = str(source_queue)
        manifest_path.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    return target


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--source-queue", required=True, help="Path to the generated .pipeline refinement queue")
    parser.add_argument("--factory-dir", required=True, help="Path to the factory directory")
    args = parser.parse_args()

    target = promote(Path(args.source_queue), Path(args.factory_dir))
    print(json.dumps({"target": str(target)}, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
