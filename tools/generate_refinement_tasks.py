#!/usr/bin/env python3
"""Generate follow-up refinement tasks from pipeline summaries."""

from __future__ import annotations

import argparse
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
import sys

if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from core import RefinementEmitter, RefinementPlanner, RefinementQueueEmitter


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--repo-root", default=".", help="Repository root containing .pipeline summaries")
    parser.add_argument("--output", default=".pipeline/refinements", help="Directory for emitted refinement tasks")
    parser.add_argument("--queue-dir", help="Optional CAR-style refinement queue output directory")
    args = parser.parse_args()

    planner = RefinementPlanner(args.repo_root)
    tasks = planner.plan()
    emitter = RefinementEmitter(args.output)
    manifest_path = emitter.write(tasks)
    payload = {"count": len(tasks), "manifest": str(manifest_path.resolve())}
    if args.queue_dir:
        queue_manifest = RefinementQueueEmitter(args.queue_dir).write(tasks)
        payload["queue_manifest"] = str(queue_manifest.resolve())
    print(json.dumps(payload, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
