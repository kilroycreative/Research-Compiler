#!/usr/bin/env python3
"""Generate a reusable lowering-pass workspace from JSON config."""

from __future__ import annotations

import argparse
import json
import os
import stat
from pathlib import Path
from typing import Any

CONFIG_BASENAME = "lowering_project.json"


def ensure_list(value: Any, field: str) -> list[Any]:
    if not isinstance(value, list) or not value:
        raise ValueError(f"{field} must be a non-empty list")
    return value


def write_file(path: Path, content: str, executable: bool = False) -> None:
    path.write_text(content, encoding="utf-8")
    if executable:
        mode = path.stat().st_mode
        path.chmod(mode | stat.S_IXUSR)


def validate_config(config: dict[str, Any]) -> dict[str, Any]:
    required = [
        "project_name",
        "product_summary",
        "repo",
        "constitution",
        "debt",
        "review",
        "factory",
    ]
    for field in required:
        if field not in config:
            raise ValueError(f"missing required field: {field}")

    constitution = config["constitution"]
    for field in ["title", "what_it_is", "invariants", "primitives"]:
        if field not in constitution:
            raise ValueError(f"constitution missing field: {field}")
    ensure_list(constitution["invariants"], "constitution.invariants")
    ensure_list(constitution["primitives"], "constitution.primitives")
    constitution.setdefault("positioning", [])
    constitution.setdefault("core_loop", [])
    constitution.setdefault("file_ownership", [])
    constitution.setdefault("done_criteria", [])

    debt = config["debt"]
    for field in ["title", "work_items", "execution_order"]:
        if field not in debt:
            raise ValueError(f"debt missing field: {field}")
    ensure_list(debt["work_items"], "debt.work_items")
    ensure_list(debt["execution_order"], "debt.execution_order")
    debt.setdefault("intro", "")
    debt.setdefault("completed_items", [])

    review = config["review"]
    for field in ["title", "how_to_use", "gates"]:
        if field not in review:
            raise ValueError(f"review missing field: {field}")
    ensure_list(review["how_to_use"], "review.how_to_use")
    ensure_list(review["gates"], "review.gates")
    review.setdefault("summary_table", None)
    review.setdefault("merge_protocol", [])

    factory = config["factory"]
    for field in ["version", "project", "repo", "risk_tiers", "risk_classification", "execution_order", "verification"]:
        if field not in factory:
            raise ValueError(f"factory missing field: {field}")
    factory.setdefault("description", "")
    factory.setdefault("completed_items", [])
    factory.setdefault("security_checks", {})
    factory.setdefault("governance_files", ["CLAUDE.md", "REVIEW_CHECKLIST.md", "factory.yaml"])
    factory.setdefault("metadata", {})

    return config


def md_list(items: list[str]) -> str:
    return "\n".join(f"- {item}" for item in items)


def render_invariant_section(invariant: dict[str, Any]) -> str:
    lines = [f"### {invariant['title']}"]
    for item in invariant.get("items", []):
        lines.append(f"- **{item['label']}** — {item['text']}")
        for detail in item.get("details", []):
            lines.append(f"  - {detail}")
    return "\n".join(lines)


def render_primitives(primitives: list[dict[str, Any]]) -> str:
    blocks: list[str] = []
    for index, primitive in enumerate(primitives, start=1):
        lines = [f"### {index}. `{primitive['name']}`", primitive["summary"], ""]
        if primitive.get("code_block"):
            lang = primitive.get("code_language", "text")
            lines.append(f"```{lang}\n{primitive['code_block']}\n```")
            lines.append("")
        if primitive.get("current_status"):
            lines.append(f"**Current status:** {primitive['current_status']}")
        if primitive.get("owner"):
            lines.append(f"**Package owner:** {primitive['owner']}")
        blocks.append("\n".join(lines).rstrip())
    return "\n\n".join(blocks)


def render_file_ownership(items: list[dict[str, Any]]) -> str:
    if not items:
        return "```\nTBD\n```"
    lines = ["```"]
    for item in items:
        lines.append(f"{item['path']}\n  {item['description']}")
        for extra in item.get("children", []):
            lines.append(f"  {extra}")
    lines.append("```")
    return "\n".join(lines)


def render_done_criteria(items: list[dict[str, Any]]) -> str:
    if not items:
        return ""
    blocks = []
    for item in items:
        lines = [f"### {item['name']} — Done When:"]
        lines.extend(f"- {entry}" for entry in item.get("criteria", []))
        blocks.append("\n".join(lines))
    return "\n\n".join(blocks)


def render_lowering_claude(config: dict[str, Any]) -> str:
    constitution = config["constitution"]
    parts = [
        f"# CLAUDE.md — {constitution['title']}",
        "",
        f"> **For any agent building {config['project_name']} features.** Read this before touching code.",
        "> Self-check: if your change violates any invariant below, stop and flag it.",
        "",
        "---",
        "",
        "## 1. What This Project Is",
        "",
        constitution["what_it_is"],
        "",
    ]
    if constitution.get("core_loop"):
        parts.extend(["**The core loop:**", md_list(constitution["core_loop"]), ""])
    if constitution.get("positioning"):
        parts.extend(["**Positioning:**", md_list(constitution["positioning"]), ""])
    parts.extend(["---", "", "## 2. Architectural Invariants", ""])
    parts.append("These must not change without explicit human sign-off.")
    parts.append("")
    for invariant in constitution["invariants"]:
        parts.append(render_invariant_section(invariant))
        parts.append("")
    parts.extend(["---", "", "## 3. Canonical Primitives", ""])
    parts.append(render_primitives(constitution["primitives"]))
    parts.extend(["", "---", "", "## 4. File Ownership Map", "", render_file_ownership(constitution.get("file_ownership", [])), ""])
    done = render_done_criteria(constitution.get("done_criteria", []))
    if done:
        parts.extend(["---", "", "## 5. What \"Done\" Looks Like", "", done, ""])
    return "\n".join(parts).rstrip() + "\n"


def render_completed_items(items: list[dict[str, Any]]) -> str:
    if not items:
        return ""
    lines = ["## Completed Work (Do Not Re-run)", ""]
    for item in items:
        refs = ", ".join(item.get("refs", []))
        suffix = f": {refs}" if refs else ""
        lines.append(f"- [DONE] {item['id']} {item['summary']}{suffix}")
    return "\n".join(lines)


def render_work_item(item: dict[str, Any]) -> str:
    lines = [f"### {item['id']}: {item['title']}", ""]
    for meta in ["priority", "primitive", "package", "effort", "status"]:
        if item.get(meta):
            label = meta.replace("_", " ").title()
            lines.append(f"**{label}:** {item[meta]}  ")
    lines.append("")
    if item.get("ground_truth"):
        lines.extend(["#### Ground Truth", *[f"- {entry}" for entry in item["ground_truth"]], ""])
    if item.get("scope"):
        lines.extend(["#### Scope To Implement", *[f"- {entry}" for entry in item["scope"]], ""])
    if item.get("acceptance"):
        lines.extend(["#### Acceptance Criteria", *[f"- [ ] {entry}" for entry in item["acceptance"]], ""])
    if item.get("files"):
        lines.extend(["#### Files", *[f"- `{entry}`" for entry in item["files"]], ""])
    return "\n".join(lines).rstrip()


def render_debt(config: dict[str, Any]) -> str:
    debt = config["debt"]
    parts = [f"# DEBT.md - {debt['title']}"]
    if debt.get("intro"):
        parts.extend(["", debt["intro"]])
    completed = render_completed_items(debt.get("completed_items", []))
    if completed:
        parts.extend(["", "---", "", completed])
    if debt["work_items"]:
        parts.extend(["", "---", ""])
        for item in debt["work_items"]:
            parts.append(render_work_item(item))
            parts.extend(["", "---", ""])
        if parts[-1] == "":
            parts.pop()
            if parts[-1] == "---":
                parts.pop()
    parts.extend(["", "## Execution Order (Compiler)", ""])
    for idx, wave in enumerate(debt["execution_order"], start=1):
        parts.append(f"{idx}. {', '.join(wave)}")
    return "\n".join(parts).rstrip() + "\n"


def render_gate(gate: dict[str, Any]) -> str:
    lines = [f"## Gate {gate['number']}: {gate['title']}", ""]
    if gate.get("applies_to"):
        lines.append(f"**Applies to:** {', '.join(gate['applies_to'])}")
    if gate.get("command"):
        lines.append(f"**Command:** `{gate['command']}`")
    if gate.get("type"):
        lines.append(f"**Type:** {gate['type']}")
    if gate.get("pass_condition"):
        lines.append(f"**Pass condition:** {gate['pass_condition']}")
    if gate.get("failure_action"):
        lines.append(f"**Failure action:** {gate['failure_action']}")
    lines.append("")
    if gate.get("description"):
        lines.extend([gate["description"], ""])
    if gate.get("code_block"):
        lines.extend([f"```{gate.get('code_language', '')}".rstrip(), gate["code_block"], "```", ""])
    if gate.get("checks"):
        lines.extend(f"- [ ] {entry}" for entry in gate["checks"])
        lines.append("")
    return "\n".join(lines).rstrip()


def render_summary_table(table: dict[str, Any]) -> str:
    headers = table["headers"]
    rows = table["rows"]
    lines = [f"| {' | '.join(headers)} |", f"| {' | '.join(['---'] * len(headers))} |"]
    for row in rows:
        lines.append(f"| {' | '.join(row)} |")
    return "\n".join(lines)


def render_review(config: dict[str, Any]) -> str:
    review = config["review"]
    parts = [f"# REVIEW_CHECKLIST.md — {review['title']}", ""]
    if review.get("intro"):
        parts.extend([review["intro"], ""])
    parts.extend(["## How to Use", "", *[f"{idx}. {item}" for idx, item in enumerate(review["how_to_use"], start=1)], ""])
    for gate in review["gates"]:
        parts.append(render_gate(gate))
        parts.append("")
    if review.get("summary_table"):
        parts.extend(["## Summary Table", "", render_summary_table(review["summary_table"]), ""])
    if review.get("merge_protocol"):
        parts.extend(["## Factory Merge Protocol", "", "```", *review["merge_protocol"], "```", ""])
    return "\n".join(parts).rstrip() + "\n"


def yaml_scalar(value: Any) -> str:
    if isinstance(value, bool):
        return "true" if value else "false"
    if value is None:
        return "null"
    if isinstance(value, (int, float)):
        return str(value)
    text = str(value)
    plain = text and all(ch not in text for ch in ":#{}[],'\"\n") and not text.startswith(("-", "@", "`", " ")) and not text.endswith(" ")
    return text if plain else json.dumps(text)


def dump_yaml(value: Any, indent: int = 0) -> str:
    prefix = " " * indent
    if isinstance(value, dict):
        lines: list[str] = []
        for key, item in value.items():
            if isinstance(item, (dict, list)):
                lines.append(f"{prefix}{key}:")
                lines.append(dump_yaml(item, indent + 2))
            else:
                lines.append(f"{prefix}{key}: {yaml_scalar(item)}")
        return "\n".join(lines)
    if isinstance(value, list):
        lines = []
        for item in value:
            if isinstance(item, (dict, list)):
                lines.append(f"{prefix}-")
                lines.append(dump_yaml(item, indent + 2))
            else:
                lines.append(f"{prefix}- {yaml_scalar(item)}")
        return "\n".join(lines)
    return f"{prefix}{yaml_scalar(value)}"


def render_factory(config: dict[str, Any]) -> str:
    return dump_yaml(config["factory"]) + "\n"


def scaffold(config: dict[str, Any], output_dir: Path) -> None:
    output_dir.mkdir(parents=True, exist_ok=True)
    write_file(output_dir / CONFIG_BASENAME, json.dumps(config, indent=2) + "\n")
    write_file(output_dir / "CLAUDE.md", render_lowering_claude(config))
    write_file(output_dir / "DEBT.md", render_debt(config))
    write_file(output_dir / "REVIEW_CHECKLIST.md", render_review(config))
    write_file(output_dir / "factory.yaml", render_factory(config))


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--config", required=True, help="Path to lowering JSON config")
    parser.add_argument("--output", required=True, help="Directory to create")
    args = parser.parse_args()

    config_path = Path(os.path.expanduser(args.config)).resolve()
    output_dir = Path(os.path.expanduser(args.output)).resolve()
    config = validate_config(json.loads(config_path.read_text(encoding="utf-8")))
    scaffold(config, output_dir)
    print(f"Created lowering workspace at {output_dir}")


if __name__ == "__main__":
    main()
