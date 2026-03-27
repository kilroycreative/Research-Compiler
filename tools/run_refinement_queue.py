#!/usr/bin/env python3
"""Run promoted refinement tickets sequentially."""

from __future__ import annotations

import argparse
import asyncio
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
import sys

if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from core import RefinementQueueRunner


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--queue-dir", required=True, help="Path to the promoted refinement queue")
    parser.add_argument("--command", required=True, help="Shell command template; supports {ticket} and {ticket_id}")
    args = parser.parse_args()

    runner = RefinementQueueRunner(args.queue_dir)
    results = asyncio.run(runner.run_command(args.command))
    print(json.dumps({"results": results}, indent=2))
    return 0 if all(item["status"] == "ok" for item in results) else 1


if __name__ == "__main__":
    raise SystemExit(main())
