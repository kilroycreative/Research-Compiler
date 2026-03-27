#!/usr/bin/env python3
"""Generate compiler initiation scripts and session packages from lowering config."""

from __future__ import annotations

import argparse
import json
import shutil
import stat
import textwrap
from pathlib import Path
from typing import Any


def write_file(path: Path, content: str, executable: bool = False) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content, encoding="utf-8")
    if executable:
        path.chmod(path.stat().st_mode | stat.S_IXUSR)


def load_config(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8"))


def resolve_repo_hint(run_root: Path, repo_hint: str) -> str:
    repo_path = Path(repo_hint).expanduser()
    if not repo_path.is_absolute():
        repo_path = (run_root / repo_path).resolve()
    return str(repo_path)


def flatten_execution_order(waves: list[list[str]]) -> list[str]:
    ordered: list[str] = []
    for wave in waves:
        ordered.extend(wave)
    return ordered


def work_item_map(config: dict[str, Any]) -> dict[str, dict[str, Any]]:
    return {item["id"]: item for item in config["debt"]["work_items"]}


def render_coordinator_package(config: dict[str, Any], repo_hint: str) -> str:
    waves = "\n".join(
        f"{idx}. {', '.join(wave)}" for idx, wave in enumerate(config["debt"]["execution_order"], start=1)
    )
    debt_ids = ", ".join(flatten_execution_order(config["debt"]["execution_order"]))
    lines = [
        "# Compiler Coordinator Session Package",
        "",
        f"Project: {config['project_name']}",
        f"Repo target hint: {repo_hint}",
        f"Product summary: {config['product_summary']}",
        "",
        "Your role:",
        "- coordinate execution against the lowering pass",
        "- keep work inside the constitution and execution order",
        "- reject speculative scope growth",
        "- route implementation questions back to the lowering artifacts first",
        "",
        "Governing files:",
        "- ../../lowering-pass/CLAUDE.md",
        "- ../../lowering-pass/DEBT.md",
        "- ../../lowering-pass/REVIEW_CHECKLIST.md",
        "- ../../lowering-pass/factory.yaml",
        "",
        "Execution order:",
        waves,
        "",
        "Work items in scope:",
        debt_ids,
        "",
        "Start rules:",
        "- read the governing files before assigning work",
        "- assign only the work items in the current wave",
        "- require verification evidence before moving an item to done",
        "- if code diverges from the constitution, stop the lane and correct scope",
    ]
    return "\n".join(lines).rstrip() + "\n"


def render_reviewer_package(config: dict[str, Any], repo_hint: str) -> str:
    gates = "\n".join(f"- Gate {gate['number']}: {gate['title']}" for gate in config["review"]["gates"])
    lines = [
        "# Compiler Reviewer Session Package",
        "",
        f"Project: {config['project_name']}",
        f"Repo target hint: {repo_hint}",
        "",
        "Your role:",
        "- review compiler output against the lowering pass",
        "- enforce REVIEW_CHECKLIST.md and factory risk tiers",
        "- reject changes that widen scope or skip verification",
        "",
        "Primary review gates:",
        gates,
        "",
        "Review protocol:",
        "- read ../../lowering-pass/REVIEW_CHECKLIST.md first",
        "- use ../../lowering-pass/factory.yaml to determine tier and required checks",
        "- confirm the implementation still matches ../../lowering-pass/CLAUDE.md",
        "- call out regressions, missing tests, and spec drift first",
    ]
    return "\n".join(lines).rstrip() + "\n"


def render_worker_package(
    config: dict[str, Any],
    repo_hint: str,
    item: dict[str, Any],
    risk: str,
    wave_number: int,
) -> str:
    ground_truth = "\n".join(f"- {entry}" for entry in item.get("ground_truth", []))
    scope = "\n".join(f"- {entry}" for entry in item.get("scope", []))
    acceptance = "\n".join(f"- [ ] {entry}" for entry in item.get("acceptance", []))
    files = "\n".join(f"- `{entry}`" for entry in item.get("files", []))
    lines = [
        "# Compiler Worker Session Package",
        "",
        f"Project: {config['project_name']}",
        f"Repo target hint: {repo_hint}",
        f"Wave: {wave_number}",
        f"Work item: {item['id']} — {item['title']}",
        f"Risk tier: {risk}",
        f"Primitive: {item.get('primitive', 'unspecified')}",
        f"Package surface: {item.get('package', 'unspecified')}",
        "",
        "Your role:",
        "- implement exactly this work item",
        "- stay inside the listed scope",
        "- use the constitution and review checklist as hard constraints",
        "- do not broaden the product beyond the chosen wedge",
        "",
        "Ground truth:",
        ground_truth or "- none provided",
        "",
        "Scope:",
        scope or "- none provided",
        "",
        "Acceptance criteria:",
        acceptance or "- [ ] none provided",
        "",
        "Files:",
        files or "- no files listed",
        "",
        "Required context:",
        "- ../../lowering-pass/CLAUDE.md",
        "- ../../lowering-pass/DEBT.md",
        "- ../../lowering-pass/REVIEW_CHECKLIST.md",
        "- ../../lowering-pass/factory.yaml",
        "",
        "Start rules:",
        "- read the governing files first",
        "- implement only this work item unless the coordinator redirects you",
        "- preserve reviewability and verification hooks",
        "- report blockers as contradictions against the lowering pass, not guesses",
    ]
    return "\n".join(lines).rstrip() + "\n"


def render_role_script(package_rel: str, repo_hint: str) -> str:
    return textwrap.dedent(
        f"""
        #!/usr/bin/env bash
        set -euo pipefail

        ROOT="$(cd "$(dirname "${{BASH_SOURCE[0]}}")/.." && pwd -P)"
        RUN_ROOT="$(cd "$ROOT/.." && pwd -P)"
        REPO_DIR="$RUN_ROOT/{repo_hint}"
        if [[ ! -d "$REPO_DIR" ]]; then
          REPO_DIR="$RUN_ROOT"
        fi

        cd "$REPO_DIR"
        cat "$ROOT/{package_rel}" | claude --print --permission-mode bypassPermissions 2>&1 | tee -a "$ROOT/logs/$(basename "${{BASH_SOURCE[0]}}" .sh).log"
        """
    ).strip() + "\n"


def render_tmux_launcher(config: dict[str, Any], script_names: list[str]) -> str:
    session = f"{config['factory'].get('project', 'compiler')}-compiler"
    lines = [
        "#!/usr/bin/env bash",
        "set -euo pipefail",
        'ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd -P)"',
        f'SESSION="{session}"',
        'mkdir -p "$ROOT/logs"',
        'tmux kill-session -t "$SESSION" 2>/dev/null || true',
        'tmux new-session -d -s "$SESSION" -n "coordinator" -c "$ROOT/.."',
        'tmux send-keys -t "$SESSION:coordinator" "$ROOT/initiation/coordinator.sh" Enter',
    ]
    for name in script_names:
        if name == "coordinator.sh":
            continue
        window = name.removesuffix(".sh")
        lines.append(f'tmux new-window -t "$SESSION" -n "{window}" -c "$ROOT/.."')
        lines.append(f'tmux send-keys -t "$SESSION:{window}" "$ROOT/initiation/{name}" Enter')
    lines.extend(
        [
            'echo "Created tmux session $SESSION"',
            'echo "Attach with: tmux attach -t $SESSION"',
        ]
    )
    return "\n".join(lines) + "\n"


def render_start_flow_script() -> str:
    return textwrap.dedent(
        """
        #!/usr/bin/env bash
        set -euo pipefail

        ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd -P)"
        cd "$ROOT"

        if ! command -v car >/dev/null 2>&1; then
          echo "car CLI not found in PATH" >&2
          exit 1
        fi

        MAX_TOTAL_TURNS="${MAX_TOTAL_TURNS:-24}"
        FORCE_NEW=0

        while [[ $# -gt 0 ]]; do
          case "$1" in
            --force-new)
              FORCE_NEW=1
              shift
              ;;
            --max-total-turns)
              MAX_TOTAL_TURNS="${2:?missing value for --max-total-turns}"
              shift 2
              ;;
            *)
              echo "usage: ./start-compiler-flow.sh [--force-new] [--max-total-turns N]" >&2
              exit 1
              ;;
          esac
        done

        car init . >/dev/null

        REPO_ID="$(basename "$ROOT" | tr '[:upper:]' '[:lower:]' | sed 's/[^a-z0-9]/-/g; s/^-*//; s/-*$//')"
        if [[ -z "$REPO_ID" ]]; then
          REPO_ID="compiler-repo"
        fi

        car hub create "$REPO_ID" --path .codex-autorunner --repo-path . --force >/dev/null

        if [[ -x .codex-autorunner/bin/lint_tickets.py ]]; then
          python3 .codex-autorunner/bin/lint_tickets.py >/dev/null
        fi

        car ticket-flow preflight --repo . --json

        START_ARGS=(ticket-flow start --repo . --max-total-turns "$MAX_TOTAL_TURNS")
        if [[ $FORCE_NEW -eq 1 ]]; then
          START_ARGS+=(--force-new)
        fi

        car "${START_ARGS[@]}"
        car ticket-flow status --repo . --json
        """
    ).strip() + "\n"


def render_status_flow_script() -> str:
    return textwrap.dedent(
        """
        #!/usr/bin/env bash
        set -euo pipefail

        cd "$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd -P)"

        if ! command -v car >/dev/null 2>&1; then
          echo "car CLI not found in PATH" >&2
          exit 1
        fi

        car ticket-flow status --repo . --json
        """
    ).strip() + "\n"


def render_stop_flow_script() -> str:
    return textwrap.dedent(
        """
        #!/usr/bin/env bash
        set -euo pipefail

        cd "$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd -P)"

        if ! command -v car >/dev/null 2>&1; then
          echo "car CLI not found in PATH" >&2
          exit 1
        fi

        car ticket-flow stop --repo .
        car ticket-flow status --repo . --json
        """
    ).strip() + "\n"


def render_repo_bootstrap_script(repo_dir: str) -> str:
    return textwrap.dedent(
        f"""
        #!/usr/bin/env bash
        set -euo pipefail

        ROOT="$(cd "$(dirname "${{BASH_SOURCE[0]}}")" && pwd -P)"
        RUN_ROOT="$(cd "$ROOT/.." && pwd -P)"
        DEFAULT_TARGET="{repo_dir}"

        TARGET="$DEFAULT_TARGET"
        FORCE=0

        while [[ $# -gt 0 ]]; do
          case "$1" in
            --force)
              FORCE=1
              shift
              ;;
            *)
              TARGET="$1"
              shift
              ;;
          esac
        done

        mkdir -p "$TARGET"
        if [[ ! -d "$TARGET/.git" ]]; then
          git -C "$TARGET" init >/dev/null 2>&1 || true
        fi

        if [[ $FORCE -ne 1 ]]; then
          for path in \
            "$TARGET/lowering-pass" \
            "$TARGET/factory/session-packages" \
            "$TARGET/factory/initiation" \
            "$TARGET/.codex-autorunner/tickets" \
            "$TARGET/.codex-autorunner/contextspace"
          do
            if [[ -e "$path" ]]; then
              echo "refusing to overwrite $path; re-run with --force" >&2
              exit 1
            fi
          done
        fi

        mkdir -p "$TARGET/factory" "$TARGET/.codex-autorunner"
        rm -rf \
          "$TARGET/lowering-pass" \
          "$TARGET/factory/session-packages" \
          "$TARGET/factory/initiation" \
          "$TARGET/.codex-autorunner/tickets" \
          "$TARGET/.codex-autorunner/contextspace"

        cp -R "$RUN_ROOT/lowering-pass" "$TARGET/lowering-pass"
        cp -R "$ROOT/session-packages" "$TARGET/factory/session-packages"
        cp -R "$ROOT/initiation" "$TARGET/factory/initiation"
        cp "$ROOT/session-manifest.json" "$TARGET/factory/session-manifest.json"
        cp "$ROOT/init-compiler.sh" "$TARGET/factory/init-compiler.sh"
        cp "$ROOT/start-compiler-flow.sh" "$TARGET/start-compiler-flow.sh"
        cp "$ROOT/start-compiler-flow.sh" "$TARGET/factory/start-compiler-flow.sh"
        cp "$ROOT/launch-humanlayer-ticket.sh" "$TARGET/factory/launch-humanlayer-ticket.sh"
        cp "$ROOT/launch-humanlayer-refinement.sh" "$TARGET/factory/launch-humanlayer-refinement.sh"
        cp "$ROOT/status-compiler-flow.sh" "$TARGET/status-compiler-flow.sh"
        cp "$ROOT/status-compiler-flow.sh" "$TARGET/factory/status-compiler-flow.sh"
        cp "$ROOT/stop-compiler-flow.sh" "$TARGET/stop-compiler-flow.sh"
        cp "$ROOT/stop-compiler-flow.sh" "$TARGET/factory/stop-compiler-flow.sh"
        cp "$ROOT/README.md" "$TARGET/factory/README.md"

        if [[ -d "$ROOT/compiler-queue/.codex-autorunner/tickets" ]]; then
          cp -R "$ROOT/compiler-queue/.codex-autorunner/tickets" "$TARGET/.codex-autorunner/"
          cp -R "$ROOT/compiler-queue/.codex-autorunner/contextspace" "$TARGET/.codex-autorunner/"
          cp "$ROOT/compiler-queue/queue-manifest.json" "$TARGET/factory/compiler-queue-manifest.json"
        fi

        echo "Bootstrapped compiler repo at $TARGET"
        echo "  lowering-pass      -> $TARGET/lowering-pass"
        echo "  factory packages   -> $TARGET/factory/session-packages"
        echo "  factory initiation -> $TARGET/factory/initiation"
        echo "  CAR queue          -> $TARGET/.codex-autorunner/tickets"
        """
    ).strip() + "\n"


def render_humanlayer_ticket_launcher() -> str:
    return textwrap.dedent(
        """
        #!/usr/bin/env bash
        set -euo pipefail

        ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd -P)"
        REPO_ROOT="${REPO_ROOT:-$ROOT/..}"
        MODEL="${MODEL:-sonnet}"
        HUMANLAYER_BIN="${HUMANLAYER_BIN:-humanlayer}"

        if [[ $# -lt 1 ]]; then
          echo "usage: ./launch-humanlayer-ticket.sh TICKET_FILE [--no-launch]" >&2
          exit 1
        fi

        python3 "$ROOT/../tools/launch_humanlayer_ticket.py" \
          --ticket "$1" \
          --repo-root "$REPO_ROOT" \
          --model "$MODEL" \
          --humanlayer-bin "$HUMANLAYER_BIN" \
          "${@:2}"
        """
    ).strip() + "\n"


def render_humanlayer_refinement_launcher() -> str:
    return textwrap.dedent(
        """
        #!/usr/bin/env bash
        set -euo pipefail

        ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd -P)"
        REPO_ROOT="${REPO_ROOT:-$ROOT/..}"
        MODEL="${MODEL:-sonnet}"
        HUMANLAYER_BIN="${HUMANLAYER_BIN:-humanlayer}"
        QUEUE_DIR="${QUEUE_DIR:-$ROOT/refinement-queue/.codex-autorunner/tickets}"

        if [[ $# -lt 1 ]]; then
          echo "usage: ./launch-humanlayer-refinement.sh RTICKET_FILE [--no-launch]" >&2
          echo "example queue dir: $QUEUE_DIR" >&2
          exit 1
        fi

        python3 "$ROOT/../tools/launch_humanlayer_ticket.py" \
          --ticket "$1" \
          --repo-root "$REPO_ROOT" \
          --model "$MODEL" \
          --humanlayer-bin "$HUMANLAYER_BIN" \
          "${@:2}"
        """
    ).strip() + "\n"


def build_manifest(config: dict[str, Any], repo_dir: str) -> dict[str, Any]:
    work_items = work_item_map(config)
    item_order = flatten_execution_order(config["debt"]["execution_order"])
    return {
        "project": config["project_name"],
        "repo": config["repo"],
        "execution_order": config["debt"]["execution_order"],
        "workers": [
            {
                "work_item": item_id,
                "risk": config["factory"]["risk_classification"].get(item_id, "unspecified"),
                "package": f"session-packages/worker-{item_id.lower()}.md",
                "initiation_script": f"initiation/worker-{item_id.lower()}.sh",
                "title": work_items[item_id]["title"],
            }
            for item_id in item_order
        ],
    }


def generate(config_path: Path, factory_dir: Path) -> None:
    config = load_config(config_path)
    run_root = factory_dir.parent.resolve()
    repo_dir = resolve_repo_hint(run_root, config["repo"])

    packages_dir = factory_dir / "session-packages"
    initiation_dir = factory_dir / "initiation"
    logs_dir = factory_dir / "logs"
    shutil.rmtree(packages_dir, ignore_errors=True)
    shutil.rmtree(initiation_dir, ignore_errors=True)
    logs_dir.mkdir(parents=True, exist_ok=True)

    item_by_id = work_item_map(config)
    wave_for_item: dict[str, int] = {}
    for wave_idx, wave in enumerate(config["debt"]["execution_order"], start=1):
        for item_id in wave:
            wave_for_item[item_id] = wave_idx

    write_file(packages_dir / "coordinator.md", render_coordinator_package(config, config["repo"]))
    write_file(packages_dir / "reviewer.md", render_reviewer_package(config, config["repo"]))

    script_names = ["coordinator.sh", "reviewer.sh"]
    write_file(
        initiation_dir / "coordinator.sh",
        render_role_script("session-packages/coordinator.md", config["repo"]),
        executable=True,
    )
    write_file(
        initiation_dir / "reviewer.sh",
        render_role_script("session-packages/reviewer.md", config["repo"]),
        executable=True,
    )

    ordered_items = flatten_execution_order(config["debt"]["execution_order"])
    for item_id in ordered_items:
        item = item_by_id[item_id]
        risk = config["factory"]["risk_classification"].get(item_id, "unspecified")
        package_name = f"worker-{item_id.lower()}.md"
        script_name = f"worker-{item_id.lower()}.sh"
        write_file(
            packages_dir / package_name,
            render_worker_package(config, config["repo"], item, risk, wave_for_item[item_id]),
        )
        write_file(
            initiation_dir / script_name,
            render_role_script(f"session-packages/{package_name}", config["repo"]),
            executable=True,
        )
        script_names.append(script_name)

    write_file(factory_dir / "session-manifest.json", json.dumps(build_manifest(config, repo_dir), indent=2) + "\n")
    write_file(factory_dir / "init-compiler.sh", render_tmux_launcher(config, script_names), executable=True)
    write_file(factory_dir / "start-compiler-flow.sh", render_start_flow_script(), executable=True)
    write_file(factory_dir / "launch-humanlayer-ticket.sh", render_humanlayer_ticket_launcher(), executable=True)
    write_file(factory_dir / "launch-humanlayer-refinement.sh", render_humanlayer_refinement_launcher(), executable=True)
    write_file(factory_dir / "status-compiler-flow.sh", render_status_flow_script(), executable=True)
    write_file(factory_dir / "stop-compiler-flow.sh", render_stop_flow_script(), executable=True)
    write_file(factory_dir / "bootstrap-compiler-repo.sh", render_repo_bootstrap_script(repo_dir), executable=True)


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--config", required=True, help="Path to lowering config JSON")
    parser.add_argument("--factory-dir", required=True, help="Factory output directory")
    args = parser.parse_args()

    generate(
        config_path=Path(args.config).expanduser().resolve(),
        factory_dir=Path(args.factory_dir).expanduser().resolve(),
    )
    print(f"Generated compiler session packages in {Path(args.factory_dir).expanduser().resolve()}")


if __name__ == "__main__":
    main()
