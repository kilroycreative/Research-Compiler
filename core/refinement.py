"""Generate follow-up refinement tasks from pipeline summaries and diagnostics."""

from __future__ import annotations

import json
import re
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any


@dataclass(frozen=True)
class RefinementTask:
    refinement_id: str
    source_task_id: str
    priority: str
    title: str
    summary: str
    recommended_scope: list[str]
    evidence: dict[str, Any]

    def to_payload(self) -> dict[str, Any]:
        return asdict(self)


class RefinementPlanner:
    """Builds concrete follow-up tasks from task summaries and diagnostics."""

    def __init__(self, repo_root: str | Path) -> None:
        self.repo_root = Path(repo_root).resolve()
        self.pipeline_root = self.repo_root / ".pipeline"

    def load_summaries(self) -> list[dict[str, Any]]:
        if not self.pipeline_root.exists():
            return []
        summaries: list[dict[str, Any]] = []
        for summary_path in sorted(self.pipeline_root.glob("*/summary.json")):
            summaries.append(json.loads(summary_path.read_text(encoding="utf-8")))
        return summaries

    def plan(self) -> list[RefinementTask]:
        tasks: list[RefinementTask] = []
        seen: set[tuple[str, str, str]] = set()
        for summary in self.load_summaries():
            diagnostics = summary.get("diagnostics", [])
            if summary.get("status") == "success" and not diagnostics:
                continue
            if diagnostics:
                for diagnostic in diagnostics:
                    key = (
                        summary.get("task_id", "unknown"),
                        diagnostic.get("code", "PIPELINE_FAILURE"),
                        diagnostic.get("message", ""),
                    )
                    if key in seen:
                        continue
                    seen.add(key)
                    tasks.append(self._task_from_diagnostic(summary, diagnostic, len(tasks) + 1))
                continue
            tasks.append(self._task_from_summary(summary, len(tasks) + 1))
        return tasks

    def _task_from_diagnostic(self, summary: dict[str, Any], diagnostic: dict[str, Any], index: int) -> RefinementTask:
        source_task_id = summary.get("task_id", "unknown")
        code = diagnostic.get("code", "PIPELINE_FAILURE")
        message = diagnostic.get("message", "Pipeline execution failed.")
        pass_name = diagnostic.get("pass_name", "unknown")
        file_path = diagnostic.get("file_path")
        priority = self._priority_for(code=code, summary=summary)
        title = f"Refine {source_task_id}: {self._humanize_code(code)}"
        summary_text = f"{message} Observed during `{pass_name}`."
        recommended_scope = self._recommended_scope(code=code, pass_name=pass_name, file_path=file_path)
        return RefinementTask(
            refinement_id=f"REFINE-{index:03d}",
            source_task_id=source_task_id,
            priority=priority,
            title=title,
            summary=summary_text,
            recommended_scope=recommended_scope,
            evidence={
                "status": summary.get("status"),
                "error": summary.get("error"),
                "diagnostic": diagnostic,
                "total_cost_usd": summary.get("total_cost_usd", 0.0),
            },
        )

    def _task_from_summary(self, summary: dict[str, Any], index: int) -> RefinementTask:
        source_task_id = summary.get("task_id", "unknown")
        error = summary.get("error", "Pipeline execution failed.")
        return RefinementTask(
            refinement_id=f"REFINE-{index:03d}",
            source_task_id=source_task_id,
            priority=self._priority_for(code="PIPELINE_FAILURE", summary=summary),
            title=f"Refine {source_task_id}: Recover failed pipeline run",
            summary=error,
            recommended_scope=[
                "Reproduce the failing task with the recorded authorized file set.",
                "Inspect pipeline diagnostics and verification evidence.",
                "Tighten or repair the failing pass before retrying the task.",
            ],
            evidence={
                "status": summary.get("status"),
                "error": error,
                "dispatch_attempts": summary.get("dispatch_attempts", []),
            },
        )

    def _priority_for(self, *, code: str, summary: dict[str, Any]) -> str:
        normalized = code.upper()
        if "SECURITY" in normalized:
            return "critical"
        if "BUDGET" in normalized:
            return "high"
        if summary.get("status") == "failed":
            return "high"
        return "medium"

    def _recommended_scope(self, *, code: str, pass_name: str, file_path: str | None) -> list[str]:
        normalized = code.upper()
        scope: list[str] = []
        if "SECURITY" in normalized:
            scope.extend(
                [
                    "Reproduce the unauthorized write and confirm the authorized file list is correct.",
                    "Tighten the runtime monitor or prompt so the task stays within scope.",
                ]
            )
        elif "BUDGET" in normalized:
            scope.extend(
                [
                    "Reduce context size or lower the task to a cheaper model tier.",
                    "Adjust execution budgets only if the task genuinely requires more cost headroom.",
                ]
            )
        else:
            scope.extend(
                [
                    f"Inspect the failing `{pass_name}` pass and reproduce the error locally.",
                    "Use the recorded diagnostics to define a narrower remediation task.",
                ]
            )
        if file_path:
            scope.append(f"Review the affected file path `{file_path}` and keep the refinement scoped to that surface.")
        return scope

    def _humanize_code(self, code: str) -> str:
        text = re.sub(r"[_\-]+", " ", code.strip()).strip()
        if not text:
            return "Pipeline failure"
        return text.title()


class RefinementEmitter:
    """Writes refinement tasks as JSON plus Markdown tickets."""

    def __init__(self, output_dir: str | Path) -> None:
        self.output_dir = Path(output_dir)
        self.output_dir.mkdir(parents=True, exist_ok=True)

    def write(self, tasks: list[RefinementTask]) -> Path:
        manifest_path = self.output_dir / "refinements.json"
        manifest_path.write_text(
            json.dumps([task.to_payload() for task in tasks], indent=2, sort_keys=True) + "\n",
            encoding="utf-8",
        )
        for task in tasks:
            ticket_path = self.output_dir / f"{task.refinement_id.lower()}-{self._slugify(task.title)}.md"
            ticket_path.write_text(self._render_ticket(task), encoding="utf-8")
        return manifest_path

    def _render_ticket(self, task: RefinementTask) -> str:
        scope = "\n".join(f"- {entry}" for entry in task.recommended_scope)
        evidence = json.dumps(task.evidence, indent=2, sort_keys=True)
        return (
            f"# {task.refinement_id}: {task.title}\n\n"
            f"- Source task: `{task.source_task_id}`\n"
            f"- Priority: `{task.priority}`\n\n"
            f"## Problem\n"
            f"{task.summary}\n\n"
            f"## Recommended Scope\n"
            f"{scope}\n\n"
            f"## Evidence\n"
            f"```json\n{evidence}\n```\n"
        )

    def _slugify(self, value: str) -> str:
        return re.sub(r"[^a-z0-9]+", "-", value.lower()).strip("-")


class RefinementQueueEmitter:
    """Writes refinement tasks as a CAR-style follow-up queue."""

    def __init__(self, queue_root: str | Path) -> None:
        self.queue_root = Path(queue_root)
        self.tickets_dir = self.queue_root / ".codex-autorunner" / "tickets"
        self.tickets_dir.mkdir(parents=True, exist_ok=True)

    def write(self, tasks: list[RefinementTask]) -> Path:
        agents_path = self.tickets_dir / "AGENTS.md"
        agents_path.write_text(
            "# Refinement Tickets\n\nThis folder contains compiler-generated follow-up tickets.\n",
            encoding="utf-8",
        )
        manifest = {
            "queue_dir": str(self.tickets_dir),
            "tickets": [],
        }
        for index, task in enumerate(tasks, start=1):
            ticket_name = f"RTICKET-{index:03d}.md"
            (self.tickets_dir / ticket_name).write_text(self._render_ticket(task), encoding="utf-8")
            manifest["tickets"].append(
                {
                    "ticket_file": ticket_name,
                    "refinement_id": task.refinement_id,
                    "source_task_id": task.source_task_id,
                    "priority": task.priority,
                }
            )
        manifest_path = self.queue_root / "queue-manifest.json"
        manifest_path.write_text(json.dumps(manifest, indent=2, sort_keys=True) + "\n", encoding="utf-8")
        return manifest_path

    def _render_ticket(self, task: RefinementTask) -> str:
        scope = "\n".join(f"- {entry}" for entry in task.recommended_scope)
        evidence = json.dumps(task.evidence, indent=2, sort_keys=True)
        return (
            "---\n"
            f'title: "{task.title}"\n'
            'agent: "codex"\n'
            "done: false\n"
            f'ticket_id: "{task.refinement_id.lower()}"\n'
            "---\n\n"
            "## Goal\n"
            f"- Resolve the follow-up issue discovered while executing `{task.source_task_id}`.\n\n"
            "## Problem\n"
            f"{task.summary}\n\n"
            "## Tasks\n"
            f"{scope}\n\n"
            "## Evidence\n"
            f"```json\n{evidence}\n```\n"
        )
