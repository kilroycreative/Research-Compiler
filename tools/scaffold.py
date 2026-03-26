#!/usr/bin/env python3
"""Create a reusable deep-loop research workspace from JSON config."""

from __future__ import annotations

import argparse
import json
import os
import re
import stat
import textwrap
from pathlib import Path
from typing import Any

CONFIG_BASENAME = "deep_loop_project.json"


def indent(text: str, spaces: int) -> str:
    prefix = " " * spaces
    return "\n".join(prefix + line if line else "" for line in text.splitlines())


def slugify(value: str) -> str:
    slug = re.sub(r"[^a-zA-Z0-9]+", "-", value.strip().lower()).strip("-")
    return slug or "deep-loop-project"


def ensure_list(value: Any, field: str) -> list[Any]:
    if not isinstance(value, list) or not value:
        raise ValueError(f"{field} must be a non-empty list")
    return value


def validate_config(config: dict[str, Any]) -> dict[str, Any]:
    required = [
        "project_name",
        "project_slug",
        "project_summary",
        "research_goal",
        "core_question",
        "atomic_win",
        "tag",
        "priority_directives",
        "directive_order",
        "directives",
        "report_sections",
        "output_target",
        "agent_groups",
    ]
    for field in required:
        if field not in config:
            raise ValueError(f"missing required field: {field}")

    directives = ensure_list(config["directives"], "directives")
    directive_ids: set[str] = set()
    for directive in directives:
        for field in ["id", "title", "overview", "questions"]:
            if field not in directive:
                raise ValueError(f"directive missing field: {field}")
        questions = ensure_list(directive["questions"], f"directive {directive['id']} questions")
        directive["questions"] = [str(item).strip() for item in questions]
        directive_id = str(directive["id"]).strip()
        if directive_id in directive_ids:
            raise ValueError(f"duplicate directive id: {directive_id}")
        directive_ids.add(directive_id)

    for directive_id in config["priority_directives"]:
        if directive_id not in directive_ids:
            raise ValueError(f"unknown priority directive: {directive_id}")

    if set(config["directive_order"]) != directive_ids:
        raise ValueError("directive_order must contain each directive id exactly once")

    groups = ensure_list(config["agent_groups"], "agent_groups")
    for group in groups:
        for field in ["name", "directives", "minimum_questions_per_directive"]:
            if field not in group:
                raise ValueError(f"agent group missing field: {field}")
        group_directives = ensure_list(group["directives"], f"agent group {group['name']} directives")
        for directive_id in group_directives:
            if directive_id not in directive_ids:
                raise ValueError(f"agent group {group['name']} references unknown directive {directive_id}")

    output_target = config["output_target"]
    for field in ["title", "description", "points"]:
        if field not in output_target:
            raise ValueError(f"output_target missing field: {field}")
    ensure_list(output_target["points"], "output_target.points")

    config.setdefault("minimum_answered_entries", 30)
    config.setdefault("minimum_meta_cycles", 3)
    config.setdefault("known_context", [])
    config.setdefault("notification_prefix", config["project_name"])
    config.setdefault("workspace_dir_hint", f"~/Desktop/{config['project_slug']}")
    config.setdefault("report_status", "In Progress")
    config.setdefault("meta_check_interval_minutes", 5)
    config.setdefault("notify_command", "openclaw")
    return config


def directive_map(config: dict[str, Any]) -> dict[str, dict[str, Any]]:
    return {directive["id"]: directive for directive in config["directives"]}


def render_directives(config: dict[str, Any]) -> str:
    directives_by_id = directive_map(config)
    blocks: list[str] = []
    for directive_id in config["directive_order"]:
        directive = directives_by_id[directive_id]
        priority = " (PRIORITY)" if directive_id in config["priority_directives"] else ""
        lines = [f"### Directive {directive_id}: {directive['title']}{priority}", directive["overview"], ""]
        for idx, question in enumerate(directive["questions"], start=1):
            lines.append(f"{idx}. {question}")
        blocks.append("\n".join(lines))
    return "\n\n".join(blocks)


def render_known_context(config: dict[str, Any]) -> str:
    if not config["known_context"]:
        return "- None documented yet."
    return "\n".join(f"- {item}" for item in config["known_context"])


def render_report_sections(config: dict[str, Any]) -> str:
    sections: list[str] = []
    for idx, section in enumerate(config["report_sections"], start=1):
        sections.append(f"## {idx}. {section}\n\n> TODO")
    return "\n\n".join(sections)


def render_output_target(config: dict[str, Any]) -> str:
    target = config["output_target"]
    bullets = "\n".join(f"- {point}" for point in target["points"])
    return textwrap.dedent(
        f"""
        ## Output Target

        The research must converge on **{target['title']}**.

        {target['description']}

        {bullets}
        """
    ).strip()


def render_program(config: dict[str, Any]) -> str:
    priority = ", ".join(config["priority_directives"])
    directive_blocks = render_directives(config)
    return (
        f"# deep-loop research program — {config['project_name']}\n\n"
        "> **This file is mutable.** The meta-agent rewrites it after every cohort analysis.\n"
        "> Each version is committed with a `meta:` prefix. The git log of this file is the\n"
        "> research methodology genealogy.\n\n"
        "**Version:** v1\n"
        "**Last rewritten by:** human\n"
        f"**Tag:** `{config['tag']}`\n\n"
        "---\n\n"
        "## Problem Statement\n\n"
        f"{config['research_goal']}\n\n"
        f"**Core question:** {config['core_question']}\n\n"
        f"**The atomic win we're searching for:** {config['atomic_win']}\n\n"
        "---\n\n"
        "## Research Directives (exhaust ALL of these)\n\n"
        f"{directive_blocks}\n\n"
        "---\n\n"
        "## Research Order\n\n"
        f"Start with priority directives {priority}. Use later directives to resolve gaps, contradictions, and implementation implications once the core picture is clear.\n\n"
        "---\n\n"
        f"{render_output_target(config)}\n\n"
        "## Meta-Analysis Recommendations (v1)\n"
    )


def render_constitution(config: dict[str, Any]) -> str:
    priority = ", ".join(config["priority_directives"])
    report_sections = "\n".join(f"- {section}" for section in config["report_sections"])
    return (
        "# deep-loop — Research Constitution\n\n"
        "Read this file fully before doing any research.\n"
        "Every rule tagged [BLOCK] is enforced. A violation invalidates the entry.\n\n"
        "---\n\n"
        "## Identity\n\n"
        "deep-loop is a two-tier autonomous domain research system running an **exploratory** research sprint.\n"
        "- **Tier 1 (you):** Pick a question, search the web, read sources, synthesize, write to `report.md` and `knowledge_index.tsv`, check completion, repeat or conclude.\n"
        "- **Tier 2 (meta-analysis):** Reads `knowledge_index.tsv` every cohort, measures coverage quality, rewrites `program.md`, commits the update.\n\n"
        "This is exploratory research, not confirmatory research. The goal is to surface what the project owner does not already know, not to validate prior beliefs.\n\n"
        "---\n\n"
        "## Research Invariants [BLOCK on violation]\n\n"
        "1. **No fabrication.** If you do not have a source for a claim, do not write it.\n"
        "2. **Search before writing.** Every new section or claim in `report.md` must be preceded by web search in the current session.\n"
        "3. **Cite everything.** Every claim in `report.md` gets a URL citation using `([Source Name](URL))`.\n"
        "4. **Record every question.** Every attempted research question goes into `knowledge_index.tsv`, including partial or conflicting answers.\n"
        "5. **One question fully before the next.** Do not start a new question while the current one is still `partial` unless stall protocol applies.\n"
        "6. **Read `process_log.md` before each new question.** Weight meta-analysis recommendations when choosing what to investigate next.\n\n"
        "---\n\n"
        "## Exploratory Research Mandate\n\n"
        "- Pursue discovered threads when a finding changes the strategy.\n"
        "- Surface unknown unknowns.\n"
        "- Question assumptions.\n"
        "- Compare architectures, operating models, and strategic consequences.\n\n"
        "---\n\n"
        "## Core Problem\n\n"
        f"{config['core_question']}\n\n"
        "---\n\n"
        "## Known Context (do not re-research these unless something changed)\n\n"
        f"{render_known_context(config)}\n\n"
        "---\n\n"
        "## Confidence Levels\n\n"
        "- **HIGH** — multiple independent sources agree, primary sources found\n"
        "- **MEDIUM** — one authoritative source or multiple secondary sources agree\n"
        "- **LOW** — one source only, no corroboration, or conflicting signals\n\n"
        "Always flag LOW confidence in `report.md` with:\n"
        "`> ⚠️ Low confidence — single source, needs verification.`\n\n"
        "---\n\n"
        "## Termination Protocol — REQUIRED\n\n"
        "Completion requires all of the following:\n"
        f"1. At least `{config['minimum_meta_cycles']}` meta-analysis cycles have run.\n"
        f"2. Priority directives `{priority}` are substantively covered.\n"
        "3. `report.md` includes substantive coverage for the following sections:\n"
        f"{report_sections}\n"
        f"4. `knowledge_index.tsv` contains at least `{config['minimum_answered_entries']}` answered entries.\n"
        "5. The output target in `program.md` is substantively written.\n\n"
        "When complete:\n"
        "```bash\n"
        "git add -A && git commit -m \"research: complete\"\n"
        "python3 notify.py --event done --val \"research complete\"\n"
        "exit\n"
        "```\n\n"
        "---\n\n"
        "## Stall Protocol\n\n"
        "If you cannot answer a question after 3 web searches:\n"
        "- Mark it `partial` in `knowledge_index.tsv` with `gaps_identified`\n"
        "- Add note in `report.md`: `> ⚠️ Unable to verify: <what was searched>`\n"
        "- Move to the next question\n"
        "- If 3+ consecutive stalls, send a stalled notification\n\n"
        "---\n\n"
        "## Files You Can Modify\n\n"
        "| File | Can modify? | Notes |\n"
        "|------|-------------|-------|\n"
        "| `report.md` | YES | Primary output |\n"
        "| `knowledge_index.tsv` | YES | Append only |\n"
        "| `process_log.md` | NO | Written by `meta_analyze.py` |\n"
        "| `program.md` | NO | Steered by human + meta-agent |\n"
        "| `AGENTS.md` | NO | Session-level instructions if present |\n\n"
        "---\n\n"
        "## Output Quality Bar\n\n"
        "Before writing a section to `report.md`, ask:\n"
        "- Would this help the owner decide what to build, defer, or reject?\n"
        "- Is every claim traceable to a source?\n"
        "- Are comparisons and tradeoffs explicit?\n"
        "- Are gaps and unknown unknowns prominent?\n"
        "- Does the finding inform the output target?\n\n"
        "If not, search more first.\n"
    )


def render_readme(config: dict[str, Any]) -> str:
    outputs = "\n".join(f"- {item}" for item in config["report_sections"])
    return (
        f"# {config['project_slug']}\n\n"
        f"{config['project_summary']}\n\n"
        "## What this produces\n\n"
        "A `report.md` with:\n"
        f"{outputs}\n\n"
        "## How to run\n\n"
        "```bash\n"
        f"cd {config['workspace_dir_hint']}\n"
        "claude --permission-mode bypassPermissions\n"
        "# then: /loop\n"
        "```\n\n"
        "Or run the tmux swarm launcher:\n\n"
        "```bash\n"
        "./swarm.sh\n"
        "```\n\n"
        "## Files\n\n"
        "| File | Purpose |\n"
        "|------|---------|\n"
        "| `deep_loop_project.json` | Project configuration for the generated workspace |\n"
        "| `CLAUDE.md` | Research constitution and invariants |\n"
        "| `program.md` | Mutable research directives |\n"
        "| `report.md` | Primary output |\n"
        "| `knowledge_index.tsv` | Audit trail of research questions |\n"
        "| `process_log.md` | Meta-analysis history |\n"
        "| `meta_analyze.py` | Meta-analysis engine |\n"
        "| `notify.py` | Project notifications |\n"
        "| `swarm.sh` | Launches parallel research agents |\n"
    )


def render_report(config: dict[str, Any]) -> str:
    return (
        f"# {config['project_name']} Research Report\n\n"
        f"> **Status:** {config['report_status']}\n"
        "> **Entries:** 0 | **Last updated:** TBD\n"
        f"> **Research tag:** `{config['tag']}`\n"
        "> **Meta-analysis version:** v1\n\n"
        f"{render_report_sections(config)}\n"
    )


def render_process_log() -> str:
    return textwrap.dedent(
        """
        # Process Log — Meta-Analysis Run History

        Each entry is written by `meta_analyze.py` after a cohort analysis.
        Do not edit manually.
        """
    ).strip() + "\n"


def render_index_header() -> str:
    return "question\tdirective\tstatus\tconfidence\tsearches\tanswer_summary\tgaps_identified\n"


def render_notify_py() -> str:
    return textwrap.dedent(
        f"""
#!/usr/bin/env python3
import argparse
import json
import pathlib
import subprocess
from datetime import datetime

CONFIG = pathlib.Path(__file__).with_name("{CONFIG_BASENAME}")
LOG = pathlib.Path("notify.log")


def load_config() -> dict:
    return json.loads(CONFIG.read_text())


def build_message(project_name: str, event: str, value: str) -> str:
    if event == "breakthrough":
        return f"{{project_name}} — major finding: {{value}}"
    if event == "done":
        return f"{{project_name}} — research complete: {{value}}"
    if event == "stalled":
        return f"{{project_name}} — stalled: {{value}}"
    if event == "milestone":
        return f"{{project_name}} — milestone: {{value}}"
    raise ValueError(f"unknown event: {{event}}")


def send(message: str) -> None:
    ts = datetime.now().strftime("%H:%M:%S")
    line = f"[{{ts}}] {{message}}"
    print(line)
    with open(LOG, "a", encoding="utf-8") as handle:
        handle.write(line + "\\n")

    config = load_config()
    command = config.get("notify_command", "openclaw")
    try:
        subprocess.run(
            [command, "system", "event", "--text", message, "--mode", "now"],
            timeout=15,
            capture_output=True,
            text=True,
        )
    except Exception as exc:
        print(f"[notify] event send failed: {{exc}}")


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--event", required=True, choices=["breakthrough", "done", "stalled", "milestone"])
    parser.add_argument("--val", type=str, default="")
    args = parser.parse_args()

    config = load_config()
    send(build_message(config["notification_prefix"], args.event, args.val))


if __name__ == "__main__":
    main()
"""
    ).strip() + "\n"


def render_meta_analyze_py() -> str:
    return textwrap.dedent(
        f"""
#!/usr/bin/env python3
'''Generic meta-analysis runner for generated deep-loop workspaces.'''

from __future__ import annotations

import argparse
import json
import pathlib
import subprocess
from datetime import datetime

CONFIG = pathlib.Path(__file__).with_name("{CONFIG_BASENAME}")
KNOWLEDGE_TSV = pathlib.Path("knowledge_index.tsv")
REPORT_MD = pathlib.Path("report.md")
PROGRAM_MD = pathlib.Path("program.md")
PROCESS_LOG = pathlib.Path("process_log.md")


def load_config() -> dict:
    return json.loads(CONFIG.read_text())


def get_version() -> int:
    if not PROGRAM_MD.exists():
        return 1
    text = PROGRAM_MD.read_text(encoding="utf-8")
    for line in text.splitlines():
        if line.startswith("**Version:**"):
            try:
                return int(line.split("v")[-1].strip())
            except ValueError:
                return 1
    return 1


def build_directive_summary(config: dict) -> str:
    parts = []
    for directive in config["directives"]:
        questions = "\\n".join(f"- {{question}}" for question in directive["questions"])
        parts.append(
            f"Directive {{directive['id']}}: {{directive['title']}}\\n{{directive['overview']}}\\n{{questions}}"
        )
    return "\\n\\n".join(parts)


def build_task() -> str:
    config = load_config()
    knowledge_content = KNOWLEDGE_TSV.read_text(encoding="utf-8") if KNOWLEDGE_TSV.exists() else "(no entries yet)"
    report_snippet = "\\n".join(REPORT_MD.read_text(encoding="utf-8").splitlines()[:160]) if REPORT_MD.exists() else "(no report yet)"
    program_content = PROGRAM_MD.read_text(encoding="utf-8") if PROGRAM_MD.exists() else "(no program yet)"
    target = config["output_target"]
    report_sections = "\\n".join(f"- {{section}}" for section in config["report_sections"])
    priority = ", ".join(config["priority_directives"])
    target_points = "\\n".join(f"- {{point}}" for point in target["points"])

    return f'''You are a research strategist for an autonomous exploratory research system.\\n\\nProject: {{config['project_name']}}\\nSummary: {{config['project_summary']}}\\nResearch goal: {{config['research_goal']}}\\nCore question: {{config['core_question']}}\\nAtomic win: {{config['atomic_win']}}\\n\\nPriority directives: {{priority}}\\n\\n## Directive map\\n{{build_directive_summary(config)}}\\n\\n## Current Knowledge Index (knowledge_index.tsv)\\n{{knowledge_content}}\\n\\n## Report Progress (first 160 lines)\\n{{report_snippet}}\\n\\n## Current Program\\n{{program_content}}\\n\\n## Output requirements\\nReport sections:\\n{{report_sections}}\\n\\nOutput target: {{target['title']}}\\n{{target['description']}}\\n{{target_points}}\\n\\n## Your Task\\nAnalyze research progress and identify the highest-value next questions. Specifically:\\n\\n1. Coverage gaps: which directives are weak or untouched?\\n2. Weak entries: which answers are low-confidence, partial, or under-sourced?\\n3. Emerging threads: what patterns in the gaps deserve follow-up?\\n4. Proposed questions: give EXACTLY 5 high-value next questions. For each include directive, why it matters, suggested search queries, and priority.\\n5. Pattern assessment: what is the emerging picture, and what is still unclear?\\n6. Recommended focus for the next 5 entries: where should effort go next and why?\\n\\nFormat as structured markdown. Be specific and actionable.\\n'''


def run_meta_analysis(dry_run: bool = False) -> str:
    task = build_task()
    print(f"[meta] Running meta-analysis (dry_run={{dry_run}})...")
    try:
        result = subprocess.run(
            ["claude", "--print", "--permission-mode", "bypassPermissions"],
            input=task,
            capture_output=True,
            text=True,
            timeout=120,
        )
        output = result.stdout.strip() or result.stderr.strip() or "(meta-analysis returned no output)"
    except subprocess.TimeoutExpired:
        output = "(meta-analysis timed out)"
    except FileNotFoundError:
        output = "(claude not available — meta-analysis skipped)"

    if dry_run:
        print("\\n=== META-ANALYSIS OUTPUT (dry run) ===")
        print(output)
        return output

    version = get_version()
    timestamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    with open(PROCESS_LOG, "a", encoding="utf-8") as handle:
        handle.write(f"\\n## Cohort Analysis v{{version}} — {{timestamp}}\\n\\n{{output}}\\n\\n---\\n")

    if PROGRAM_MD.exists():
        text = PROGRAM_MD.read_text(encoding="utf-8")
        new_version = version + 1
        text = text.replace(f"**Version:** v{{version}}", f"**Version:** v{{new_version}}")
        text = replace_last_rewriter(text, new_version, timestamp)
        marker = "## Meta-Analysis Recommendations"
        block = f"## Meta-Analysis Recommendations (v{{new_version}})\\n\\n{{output}}\\n"
        if marker in text:
            text = text.split(marker)[0].rstrip() + "\\n\\n" + block
        else:
            text = text.rstrip() + "\\n\\n" + block
        PROGRAM_MD.write_text(text, encoding="utf-8")

    try:
        subprocess.run(["git", "add", "process_log.md", "program.md"], capture_output=True, text=True)
        subprocess.run(["git", "commit", "-m", f"meta: cohort analysis v{{version + 1}}"], capture_output=True, text=True)
    except Exception:
        pass

    print(f"[meta] Done. process_log.md updated, program.md bumped to v{{version + 1}}")
    return output


def replace_last_rewriter(text: str, new_version: int, timestamp: str) -> str:
    replacement = f"**Last rewritten by:** meta-analysis v{{new_version}} ({{timestamp}})"
    lines = []
    replaced = False
    for line in text.splitlines():
        if line.startswith("**Last rewritten by:**"):
            lines.append(replacement)
            replaced = True
        else:
            lines.append(line)
    if not replaced:
        lines.insert(3, replacement)
    return "\\n".join(lines)


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args()
    run_meta_analysis(dry_run=args.dry_run)


if __name__ == "__main__":
    main()
"""
    ).strip() + "\n"


def render_swarm(config: dict[str, Any]) -> str:
    session = config.get("swarm_session_name", slugify(config["project_slug"]))
    dir_hint = config["workspace_dir_hint"]
    if dir_hint.startswith("~/"):
        dir_hint = "${HOME}/" + dir_hint[2:]

    lines = [
        "#!/usr/bin/env bash",
        "set -euo pipefail",
        "",
        f'SESSION="{session}"',
        f'DIR="{dir_hint}"',
        "",
        'echo "=== deep-loop research swarm ==="',
        'echo "Directory: $DIR"',
        'echo ""',
        "",
        'tmux kill-session -t "$SESSION" 2>/dev/null && echo "Killed existing session" || true',
        "",
        f'tmux new-session -d -s "$SESSION" -n "{config["agent_groups"][0]["name"]}" -c "$DIR"',
    ]

    for group in config["agent_groups"][1:]:
        lines.append(f'tmux new-window   -t "$SESSION"   -n "{group["name"]}" -c "$DIR"')

    lines.extend(
        [
            'tmux new-window   -t "$SESSION"   -n "meta"    -c "$DIR"',
            'tmux new-window   -t "$SESSION"   -n "monitor" -c "$DIR"',
            "",
            f'echo "Created tmux session \'$SESSION\' with {len(config["agent_groups"]) + 2} windows"',
            "sleep 1",
            "",
        ]
    )

    for index, group in enumerate(config["agent_groups"], start=1):
        directive_labels = "+".join(group["directives"])
        lines.extend(
            [
                f'echo "Launching {group["name"]} ({directive_labels})..."',
                f'tmux send-keys -t "$SESSION:{group["name"]}" "cat {group["name"]}-prompt.md | claude --print --permission-mode bypassPermissions 2>&1 | tee {group["name"]}.log" Enter',
            ]
        )
        if index < len(config["agent_groups"]):
            lines.extend(["sleep 3", ""])

    lines.extend(
        [
            "",
            'echo "Launching meta-agent..."',
            'tmux send-keys -t "$SESSION:meta" "cat meta-prompt.md | claude --print --permission-mode bypassPermissions 2>&1 | tee meta.log" Enter',
            "",
            """tmux send-keys -t "$SESSION:monitor" "watch -n 20 'echo \\\"=== \\$(date) ===\\\"; echo; echo \\\"-- knowledge entries --\\\"; wc -l knowledge_index.tsv 2>/dev/null; echo; echo \\\"-- partial reports --\\\"; ls partial-report-*.md 2>/dev/null || echo none; echo; echo \\\"-- recent commits --\\\"; git log --oneline -6 2>/dev/null; echo; echo \\\"-- log sizes --\\\"; wc -l *.log 2>/dev/null'" Enter""",
            "",
            'echo ""',
            'echo "Attach: tmux attach -t $SESSION"',
            'echo "Kill:   tmux kill-session -t $SESSION"',
        ]
    )

    return "\n".join(lines) + "\n"


def render_agent_prompt(config: dict[str, Any], group: dict[str, Any]) -> str:
    directives_by_id = directive_map(config)
    bullets = []
    partial_reports = []
    for directive_id in group["directives"]:
        directive = directives_by_id[directive_id]
        bullets.append(f"- Directive {directive_id}: {directive['title']} ({directive['overview']})")
        partial_reports.append(f"partial-report-{directive_id}.md")
    bullet_block = "\n".join(bullets)
    first_directive = directives_by_id[group["directives"][0]]
    start_question = group.get("start_question", first_directive["questions"][0])
    return (
        "Read `CLAUDE.md` for the research constitution and rules. "
        f"Your job: research directives {' + '.join(group['directives'])} from `program.md`.\n\n"
        f"{bullet_block}\n\n"
        "Rules:\n"
        f"- Write findings to {', '.join(partial_reports)}\n"
        "- Append to `knowledge_index.tsv` (append only, never overwrite)\n"
        f"- Commit after each entry: `git add -A && git commit -m \"{group['name']}: SLUG\"`\n"
        f"- Send milestone when done: `python3 notify.py --event milestone --val \"{group['name']} complete\"`\n"
        f"- Minimum {group['minimum_questions_per_directive']} questions per directive\n"
        "- Search before writing. Cite everything.\n\n"
        f"Start now with Directive {first_directive['id']}, Question 1: {start_question}\n"
    )


def render_meta_prompt(config: dict[str, Any]) -> str:
    partials = ", ".join(f"partial-report-{directive_id}.md" for directive_id in config["directive_order"])
    return (
        f"You are the meta-analysis and synthesis agent for a parallel research swarm on {config['project_name']}.\n\n"
        f"The research agents are writing to {partials} and appending to `knowledge_index.tsv`.\n\n"
        "Your job:\n"
        "1. Run `python3 meta_analyze.py --dry-run` now as a baseline pass.\n"
        f"2. Every {config['meta_check_interval_minutes']} minutes check progress.\n"
        "3. When all partial reports exist, merge them into `report.md`.\n"
        f"4. Write the `{config['output_target']['title']}` section based on cross-cutting findings.\n"
        "5. Run final meta-analysis: `python3 meta_analyze.py`.\n"
        "6. Commit: `git add -A && git commit -m \"synthesis: complete report.md from swarm output\"`.\n"
        "7. Send: `python3 notify.py --event done --val \"report.md ready\"`.\n\n"
        "If a partial report reveals a major contradiction or strategy change, send a breakthrough notification immediately.\n"
    )


def write_file(path: Path, content: str, executable: bool = False) -> None:
    path.write_text(content, encoding="utf-8")
    if executable:
        mode = path.stat().st_mode
        path.chmod(mode | stat.S_IXUSR)


def scaffold(config: dict[str, Any], output_dir: Path) -> None:
    output_dir.mkdir(parents=True, exist_ok=True)
    write_file(output_dir / CONFIG_BASENAME, json.dumps(config, indent=2) + "\n")
    write_file(output_dir / "README.md", render_readme(config))
    write_file(output_dir / "CLAUDE.md", render_constitution(config))
    write_file(output_dir / "program.md", render_program(config))
    write_file(output_dir / "report.md", render_report(config))
    write_file(output_dir / "process_log.md", render_process_log())
    write_file(output_dir / "knowledge_index.tsv", render_index_header())
    write_file(output_dir / "notify.py", render_notify_py(), executable=True)
    write_file(output_dir / "meta_analyze.py", render_meta_analyze_py(), executable=True)
    write_file(output_dir / "swarm.sh", render_swarm(config), executable=True)
    for group in config["agent_groups"]:
        write_file(output_dir / f"{group['name']}-prompt.md", render_agent_prompt(config, group))
    write_file(output_dir / "meta-prompt.md", render_meta_prompt(config))


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--config", required=True, help="Path to deep-loop JSON config")
    parser.add_argument("--output", required=True, help="Directory to create")
    args = parser.parse_args()

    config_path = Path(os.path.expanduser(args.config)).resolve()
    output_dir = Path(os.path.expanduser(args.output)).resolve()
    config = validate_config(json.loads(config_path.read_text(encoding="utf-8")))
    scaffold(config, output_dir)
    print(f"Created deep-loop workspace at {output_dir}")


        
if __name__ == "__main__":
    main()
