#!/usr/bin/env python3
"""Draft lowering_config.json from research artifacts."""

from __future__ import annotations

import argparse
import json
import re
import subprocess
import sys
import textwrap
from pathlib import Path

from lowering_scaffold import validate_config


def read_text(path: Path) -> str:
    return path.read_text(encoding="utf-8") if path.exists() else ""


def extract_json(text: str) -> dict:
    fenced = re.search(r"```json\s*(\{.*\})\s*```", text, re.DOTALL)
    if fenced:
        return json.loads(fenced.group(1))

    start = text.find("{")
    end = text.rfind("}")
    if start == -1 or end == -1 or end <= start:
        raise ValueError("no JSON object found in model output")
    return json.loads(text[start : end + 1])


def build_prompt(
    research_config: dict,
    lowering_template: dict,
    report_md: str,
    program_md: str,
    knowledge_index_tsv: str,
) -> str:
    return textwrap.dedent(
        f"""
        You are converting research output into a lowering-pass config for a product compiler.

        Return JSON only. No prose. No markdown fence unless unavoidable.

        Your output must be valid JSON matching the same schema and shape as the provided lowering template.

        Goals:
        - turn the research into a product-specific lowering config
        - keep the scope narrow and realistic for an initial build
        - encode clear constitutions, primitives, work items, review gates, and factory execution order
        - ensure compiler workers can act on the work items without reinterpretation

        Rules:
        - ground all product claims in the research report
        - if a detail is unclear, keep a conservative placeholder instead of inventing facts
        - preserve existing top-level structure from the lowering template
        - keep repo as-is unless the research explicitly implies a different target
        - create 3 to 6 concrete DEBT work items
        - each work item must include specific scope, acceptance criteria, and files
        - risk_classification must cover every DEBT item
        - execution_order must reference every DEBT item exactly once
        - review gates should stay generic but reflect the actual product risks from research
        - factory metadata should include source="research-handoff"

        Research config:
        {json.dumps(research_config, indent=2)}

        Lowering template:
        {json.dumps(lowering_template, indent=2)}

        program.md:
        {program_md}

        knowledge_index.tsv:
        {knowledge_index_tsv}

        report.md:
        {report_md}
        """
    ).strip()


def run_claude(prompt: str) -> str:
    try:
        result = subprocess.run(
            ["claude", "--print", "--permission-mode", "bypassPermissions"],
            input=prompt,
            text=True,
            capture_output=True,
            timeout=240,
            check=False,
        )
    except FileNotFoundError as exc:
        raise RuntimeError("claude CLI is not available") from exc

    output = result.stdout.strip() or result.stderr.strip()
    if not output:
        raise RuntimeError("claude returned no output")
    return output


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--report", required=True, help="Path to research/report.md")
    parser.add_argument("--program", required=True, help="Path to research/program.md")
    parser.add_argument("--knowledge-index", required=True, help="Path to research/knowledge_index.tsv")
    parser.add_argument("--research-config", required=True, help="Path to research_config.json")
    parser.add_argument("--lowering-template", required=True, help="Path to current lowering_config.json template")
    parser.add_argument("--output", required=True, help="Path to write drafted lowering_config.json")
    args = parser.parse_args()

    report_path = Path(args.report).expanduser().resolve()
    program_path = Path(args.program).expanduser().resolve()
    index_path = Path(args.knowledge_index).expanduser().resolve()
    research_config_path = Path(args.research_config).expanduser().resolve()
    lowering_template_path = Path(args.lowering_template).expanduser().resolve()
    output_path = Path(args.output).expanduser().resolve()

    research_config = json.loads(read_text(research_config_path))
    lowering_template = json.loads(read_text(lowering_template_path))
    prompt = build_prompt(
        research_config=research_config,
        lowering_template=lowering_template,
        report_md=read_text(report_path),
        program_md=read_text(program_path),
        knowledge_index_tsv=read_text(index_path),
    )

    raw = run_claude(prompt)
    drafted = extract_json(raw)
    drafted.setdefault("factory", {}).setdefault("metadata", {})
    drafted["factory"]["metadata"]["source"] = "research-handoff"

    validated = validate_config(drafted)
    output_path.write_text(json.dumps(validated, indent=2) + "\n", encoding="utf-8")
    print(f"Drafted lowering config at {output_path}")


if __name__ == "__main__":
    try:
        main()
    except Exception as exc:
        print(f"handoff failed: {exc}", file=sys.stderr)
        raise
