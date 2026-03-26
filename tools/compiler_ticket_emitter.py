#!/usr/bin/env python3
"""Emit CAR-compatible compiler ticket queues from lowering config."""

from __future__ import annotations

import argparse
import json
import re
import shutil
import stat
import textwrap
from pathlib import Path
from typing import Any


TICKETS_AGENTS_MD = """<!-- CAR:TICKETS_AGENTS -->
# Tickets — AGENTS

This folder is the authoritative ticket queue for this repo/worktree.

## Ticket files
- Store work items as `TICKET-###*.md` (ordered by number).
- Keep frontmatter `done: true|false` in sync with completion.
- After edits, lint tickets: `python3 .codex-autorunner/bin/lint_tickets.py`.

## Ticket CLI (portable)
- List: `python3 .codex-autorunner/bin/ticket_tool.py list`
- Create: `python3 .codex-autorunner/bin/ticket_tool.py create --title "..." --agent codex`
- Insert gap: `python3 .codex-autorunner/bin/ticket_tool.py insert --before N`
- Move block: `python3 .codex-autorunner/bin/ticket_tool.py move --start A --end B --to T`
- Lint: `python3 .codex-autorunner/bin/ticket_tool.py lint`

## Ticket flow (runner)
- See `.codex-autorunner/TICKET_FLOW_QUICKSTART.md` for `car flow ticket_flow ...` commands.
"""


def write_file(path: Path, content: str, executable: bool = False) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content, encoding="utf-8")
    if executable:
        path.chmod(path.stat().st_mode | stat.S_IXUSR)


def load_config(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8"))


def slugify(value: str) -> str:
    return re.sub(r"[^a-z0-9]+", "_", value.lower()).strip("_")


def resolve_repo_hint(run_root: Path, repo_hint: str) -> str:
    repo_path = Path(repo_hint).expanduser()
    if not repo_path.is_absolute():
        repo_path = (run_root / repo_hint).resolve()
    return str(repo_path)


def item_map(config: dict[str, Any]) -> dict[str, dict[str, Any]]:
    return {item["id"]: item for item in config["debt"]["work_items"]}


def flatten_waves(waves: list[list[str]]) -> list[str]:
    ordered: list[str] = []
    for wave in waves:
        ordered.extend(wave)
    return ordered


def verification_commands(config: dict[str, Any], risk: str) -> list[str]:
    verification = config.get("factory", {}).get("verification", {})
    commands: list[str] = []
    for key in ["lint", "typecheck", "tests"]:
        command = verification.get(key)
        if command:
            commands.append(command)

    for gate in config.get("review", {}).get("gates", []):
        if gate.get("command") and risk in gate.get("applies_to", []):
            commands.append(gate["command"])

    unique: list[str] = []
    seen: set[str] = set()
    for command in commands:
        if command not in seen:
            unique.append(command)
            seen.add(command)
    return unique


def render_active_context(config: dict[str, Any], repo_hint: str) -> str:
    waves = "\n".join(
        f"- wave {idx}: {', '.join(wave)}"
        for idx, wave in enumerate(config["debt"]["execution_order"], start=1)
    )
    lines = [
        "# Active Context",
        "",
        "Objective: execute the lowering pass as a compiler work queue against the target repo.",
        "",
        f"Project: {config['project_name']}",
        f"Repo target hint: {repo_hint}",
        f"Product summary: {config['product_summary']}",
        "",
        "Compiler source of truth:",
        "- `../../lowering-pass/CLAUDE.md`",
        "- `../../lowering-pass/DEBT.md`",
        "- `../../lowering-pass/REVIEW_CHECKLIST.md`",
        "- `../../lowering-pass/factory.yaml`",
        "",
        "Execution waves:",
        waves,
        "",
        "Hard constraints:",
        "- only execute work items present in the lowering pass",
        "- do not widen scope beyond the chosen wedge",
        "- enforce review gates before marking tickets done",
        "- use the generated session packages in `../../factory/session-packages/`",
    ]
    return "\n".join(lines).rstrip() + "\n"


def render_spec(config: dict[str, Any]) -> str:
    primitives = "\n".join(
        f"- {primitive['name']}: {primitive['summary']}"
        for primitive in config["constitution"]["primitives"]
    )
    lines = [
        "# Spec",
        "",
        "## Product",
        config["constitution"]["what_it_is"],
        "",
        "## Core Loop",
        *[f"- {item}" for item in config["constitution"].get("core_loop", [])],
        "",
        "## Positioning",
        *[f"- {item}" for item in config["constitution"].get("positioning", [])],
        "",
        "## Canonical Primitives",
        primitives,
    ]
    return "\n".join(lines).rstrip() + "\n"


def render_decisions(config: dict[str, Any]) -> str:
    lines = ["# Decisions", ""]
    for invariant in config["constitution"]["invariants"]:
        lines.append(f"- {invariant['title']} is a hard invariant.")
        for item in invariant.get("items", []):
            lines.append(f"- {item['label']}: {item['text']}")
    if config["constitution"].get("done_criteria"):
        lines.append("- Completion is defined by the lowering-pass done criteria, not by code volume.")
    return "\n".join(lines).rstrip() + "\n"


def render_ticket(
    config: dict[str, Any],
    item: dict[str, Any],
    index: int,
    wave_number: int,
    risk: str,
) -> str:
    ticket_id = f"tkt_compile_{slugify(config['factory'].get('project', config['project_name']))}_{item['id'].lower()}"
    tasks = "\n".join(f"- {entry}" for entry in item.get("scope", []))
    deliverables = "\n".join(f"- {entry}" for entry in item.get("acceptance", []))
    constraints = [
        f"wave: {wave_number}",
        f"risk tier: {risk}",
        f"primitive: {item.get('primitive', 'unspecified')}",
        "do not widen scope beyond this work item",
        "read the linked session package before editing code",
        "mark done only after required verification is recorded",
    ]
    verification = verification_commands(config, risk)
    verification_block = "\n".join(f"- `{command}`" for command in verification) if verification else "- record manual verification only"
    files = "\n".join(f"- `{entry}`" for entry in item.get("files", []))
    ground_truth = "\n".join(f"- {entry}" for entry in item.get("ground_truth", []))
    package_name = f"worker-{item['id'].lower()}.md"
    script_name = f"worker-{item['id'].lower()}.sh"

    lines = [
        "---",
        f'title: "{item["title"]}"',
        'agent: "codex"',
        "done: false",
        f'ticket_id: "{ticket_id}"',
        "---",
        "",
        "## Goal",
        f"- Execute `{item['id']}` from the lowering pass for wave {wave_number}.",
        "",
        "## Tasks",
        tasks or "- no scope listed",
        "",
        "## Deliverables",
        deliverables or "- no acceptance criteria listed",
        "",
        "## Constraints",
        *[f"- {entry}" for entry in constraints],
        "",
        "## Ground Truth",
        ground_truth or "- none provided",
        "",
        "## Files",
        files or "- none listed",
        "",
        "## Session Package",
        f"- `../../factory/session-packages/{package_name}`",
        f"- `../../factory/initiation/{script_name}`",
        "",
        "## Verification",
        verification_block,
        "",
        "## Hand-off Notes",
        "- Compare the implementation against `../../lowering-pass/CLAUDE.md`.",
        "- Use `../../lowering-pass/REVIEW_CHECKLIST.md` and `../../lowering-pass/factory.yaml` for final gate checks.",
        "- If this ticket blocks a later wave, record the exact blocker before stopping.",
    ]
    return "\n".join(lines).rstrip() + "\n"


def render_queue_readme(config: dict[str, Any]) -> str:
    return textwrap.dedent(
        f"""
        # Compiler Queue

        This folder contains a generated CAR-compatible ticket queue for `{config['project_name']}`.

        Contents:
        - `.codex-autorunner/tickets/` — ordered compiler tickets generated from DEBT waves
        - `.codex-autorunner/contextspace/` — active context, spec, and decisions derived from the lowering pass
        - `queue-manifest.json` — machine-readable mapping from DEBT items to emitted tickets
        - `install-into-repo.sh` — stages the queue into the target repo's `.codex-autorunner/`

        Use `install-into-repo.sh` when the target repo is ready to receive the queue.
        """
    ).strip() + "\n"


def render_install_script(repo_dir: str) -> str:
    return textwrap.dedent(
        f"""
        #!/usr/bin/env bash
        set -euo pipefail

        ROOT="$(cd "$(dirname "${{BASH_SOURCE[0]}}")" && pwd -P)"
        DEFAULT_REPO="{repo_dir}"
        TARGET="${{1:-$DEFAULT_REPO}}"

        mkdir -p "$TARGET/.codex-autorunner"
        rm -rf "$TARGET/.codex-autorunner/tickets" "$TARGET/.codex-autorunner/contextspace"
        cp -R "$ROOT/.codex-autorunner/tickets" "$TARGET/.codex-autorunner/"
        cp -R "$ROOT/.codex-autorunner/contextspace" "$TARGET/.codex-autorunner/"

        echo "Installed compiler queue into $TARGET/.codex-autorunner"
        if [[ -x "$TARGET/.codex-autorunner/bin/lint_tickets.py" ]]; then
          python3 "$TARGET/.codex-autorunner/bin/lint_tickets.py"
        else
          echo "lint skipped: $TARGET/.codex-autorunner/bin/lint_tickets.py not found"
        fi
        """
    ).strip() + "\n"


def build_manifest(
    config: dict[str, Any],
    wave_for_item: dict[str, int],
) -> dict[str, Any]:
    ordered_items = flatten_waves(config["debt"]["execution_order"])
    return {
        "project": config["project_name"],
        "repo": config["repo"],
        "queue_dir": "compiler-queue/.codex-autorunner/tickets",
        "tickets": [
            {
                "ticket_file": f"TICKET-{index:03d}.md",
                "work_item": item_id,
                "wave": wave_for_item[item_id],
                "risk": config["factory"]["risk_classification"].get(item_id, "unspecified"),
            }
            for index, item_id in enumerate(ordered_items, start=1)
        ],
    }


def generate(config_path: Path, factory_dir: Path) -> None:
    config = load_config(config_path)
    run_root = factory_dir.parent.resolve()
    repo_dir = resolve_repo_hint(run_root, config["repo"])

    queue_root = factory_dir / "compiler-queue"
    tickets_dir = queue_root / ".codex-autorunner" / "tickets"
    context_dir = queue_root / ".codex-autorunner" / "contextspace"
    shutil.rmtree(queue_root, ignore_errors=True)

    item_by_id = item_map(config)
    wave_for_item: dict[str, int] = {}
    for wave_idx, wave in enumerate(config["debt"]["execution_order"], start=1):
        for item_id in wave:
            wave_for_item[item_id] = wave_idx

    write_file(queue_root / "README.md", render_queue_readme(config))
    write_file(queue_root / "install-into-repo.sh", render_install_script(repo_dir), executable=True)
    write_file(tickets_dir / "AGENTS.md", TICKETS_AGENTS_MD)
    write_file(context_dir / "active_context.md", render_active_context(config, config["repo"]))
    write_file(context_dir / "spec.md", render_spec(config))
    write_file(context_dir / "decisions.md", render_decisions(config))

    ordered_items = flatten_waves(config["debt"]["execution_order"])
    for index, item_id in enumerate(ordered_items, start=1):
        item = item_by_id[item_id]
        risk = config["factory"]["risk_classification"].get(item_id, "unspecified")
        ticket_name = f"TICKET-{index:03d}.md"
        write_file(tickets_dir / ticket_name, render_ticket(config, item, index, wave_for_item[item_id], risk))

    write_file(
        queue_root / "queue-manifest.json",
        json.dumps(build_manifest(config, wave_for_item), indent=2) + "\n",
    )


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--config", required=True, help="Path to lowering config JSON")
    parser.add_argument("--factory-dir", required=True, help="Factory output directory")
    args = parser.parse_args()

    generate(
        config_path=Path(args.config).expanduser().resolve(),
        factory_dir=Path(args.factory_dir).expanduser().resolve(),
    )
    print(f"Generated compiler ticket queue in {(Path(args.factory_dir).expanduser().resolve() / 'compiler-queue')}")


if __name__ == "__main__":
    main()
