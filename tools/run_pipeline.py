#!/usr/bin/env python3
"""Run the compiler pipeline from a JSON request file."""

from __future__ import annotations

import argparse
import asyncio
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from core import (
    ActionCache,
    EventStore,
    ModelProvider,
    Pipeline,
    PipelineRequest,
    VerificationRunner,
    WorktreeManager,
    build_executor,
)
from core.pipeline import ExecutionResult


class NullExecutor:
    """Executor placeholder that expects a patch artifact to be provided upfront."""

    async def execute(self, plan, workspace):
        patch_path = workspace / ".pipeline" / f"{plan.task_id}.patch"
        if not patch_path.exists():
            raise RuntimeError(
                f"no executor configured and no patch artifact found at {patch_path}; provide a real executor"
            )
        return ExecutionResult(
            patch=patch_path.read_text(encoding="utf-8"),
            touched_files=[],
            metadata={"executor": "null", "patch_path": str(patch_path)},
        )


async def run(payload: dict, cache_path: Path, event_path: Path) -> dict:
    request = PipelineRequest.model_validate(payload)
    executor = build_executor(request.executor) if request.executor else NullExecutor()
    pipeline = Pipeline(
        executor=executor,
        action_cache=ActionCache(cache_path),
        verifier=VerificationRunner(),
        event_store=EventStore(event_path),
        worktree_manager=WorktreeManager(request.repo_root),
    )
    result = await pipeline.run(request)
    return {
        "cache_hit": result.cache_hit,
        "cache_key": result.cache_key,
        "workspace": result.workspace,
        "touched_files": result.touched_files,
        "verification": result.verification,
    }


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--request", required=True, help="Path to a PipelineRequest JSON file")
    parser.add_argument("--cache-db", default="action_cache.db", help="Path to the action cache SQLite database")
    parser.add_argument("--events", default="events.jsonl", help="Path to the JSONL event store")
    parser.add_argument("--provider", choices=[item.value for item in ModelProvider], help="Override executor provider")
    parser.add_argument("--provider-model", help="Override executor model")
    parser.add_argument("--provider-command", help="Override CLI command path")
    parser.add_argument("--provider-base-url", help="Override OpenAI-compatible base URL")
    parser.add_argument("--provider-api-key-env", help="Override API key env var")
    args = parser.parse_args()
    request_path = Path(args.request).expanduser().resolve()
    payload = json.loads(request_path.read_text(encoding="utf-8"))
    if args.provider:
        executor_payload = payload.get("executor", {})
        executor_payload["provider"] = args.provider
        if args.provider_model:
            executor_payload["model"] = args.provider_model
        if args.provider_command:
            executor_payload["command"] = args.provider_command
        if args.provider_base_url:
            executor_payload["base_url"] = args.provider_base_url
        if args.provider_api_key_env:
            executor_payload["api_key_env"] = args.provider_api_key_env
        payload["executor"] = executor_payload

    result = asyncio.run(
        run(
            payload=payload,
            cache_path=Path(args.cache_db).expanduser().resolve(),
            event_path=Path(args.events).expanduser().resolve(),
        )
    )
    print(json.dumps(result, indent=2))


if __name__ == "__main__":
    main()
