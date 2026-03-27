#!/usr/bin/env python3
"""Launch a HumanLayer session for a generated ticket inside a dedicated worktree."""

from __future__ import annotations

import argparse
import json
import re
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from core import HumanLayerRuntimeAdapter, ResourceConstraints, ResourceLimits, SandboxType
from core.ir import ExecutionPlan


def parse_ticket(ticket_path: Path) -> dict[str, object]:
    text = ticket_path.read_text(encoding="utf-8")
    title_match = re.search(r'^title:\s*"(.+)"\s*$', text, re.MULTILINE)
    files_block = re.search(r"^## Files\n(?P<body>(?:- `.+`\n)+)", text, re.MULTILINE)
    files: list[str] = []
    if files_block:
        for line in files_block.group("body").splitlines():
            match = re.search(r"`([^`]+)`", line)
            if match:
                files.append(match.group(1))
    return {
        "title": title_match.group(1) if title_match else ticket_path.stem,
        "authorized_files": files or ["README.md"],
        "body": text,
    }


def resolve_head(repo_root: Path) -> str:
    result = subprocess.run(
        ["git", "rev-parse", "HEAD"],
        cwd=repo_root,
        capture_output=True,
        text=True,
        check=False,
    )
    if result.returncode != 0:
        raise SystemExit(result.stderr.strip() or "failed to resolve HEAD")
    return result.stdout.strip()


def build_plan(repo_root: Path, ticket_path: Path, model: str) -> ExecutionPlan:
    ticket = parse_ticket(ticket_path)
    return ExecutionPlan(
        task_id=ticket_path.stem.lower(),
        base_commit=resolve_head(repo_root),
        authorized_files=ticket["authorized_files"],
        constitution=str(ticket["body"]),
        verification_contracts=[{"kind": "pass_to_pass", "selectors": [{"selector": "tests"}]}],
        model_id=model,
        sandbox_type=SandboxType.WORKTREE,
        resource_limits=ResourceLimits(max_runtime_seconds=900, max_memory_mb=2048, max_cpu_count=2),
        resource_constraints=ResourceConstraints(),
    )


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--ticket", required=True, help="Path to the generated compiler or refinement ticket")
    parser.add_argument("--repo-root", default=".", help="Target repository root")
    parser.add_argument("--model", default="sonnet", help="HumanLayer model name")
    parser.add_argument("--humanlayer-bin", default="humanlayer", help="HumanLayer CLI binary")
    parser.add_argument("--no-launch", action="store_true", help="Create the worktree without launching HumanLayer")
    args = parser.parse_args()

    repo_root = Path(args.repo_root).expanduser().resolve()
    ticket_path = Path(args.ticket).expanduser().resolve()
    adapter = HumanLayerRuntimeAdapter(
        repo_root,
        humanlayer_bin=args.humanlayer_bin,
        model=args.model,
        auto_launch=not args.no_launch,
    )
    plan = build_plan(repo_root, ticket_path, args.model)
    session = __import__("asyncio").run(adapter.execute(plan))
    print(
        json.dumps(
            {
                "workspace": str(session.workspace),
                "cleanup_token": session.cleanup_token,
                "telemetry": adapter.telemetry(session),
            },
            indent=2,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
