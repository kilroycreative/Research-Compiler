"""Structured diagnostics and task summary generation."""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Literal

from .ir import ContextSlice


@dataclass(frozen=True)
class Diagnostic:
    level: Literal["warning", "error"]
    code: str
    message: str
    pass_name: str
    file_path: str | None = None
    line: int | None = None
    details: dict[str, Any] = field(default_factory=dict)

    def to_payload(self) -> dict[str, Any]:
        payload = {
            "level": self.level,
            "code": self.code,
            "message": self.message,
            "pass_name": self.pass_name,
            "details": self.details,
        }
        if self.file_path is not None:
            payload["file_path"] = self.file_path
        if self.line is not None:
            payload["line"] = self.line
        return payload


class SourceMapper:
    """Best-effort mapping from touched files and exceptions to context slices."""

    def map_to_slice(
        self,
        *,
        touched_files: list[str],
        context_slices: list[ContextSlice],
        pass_name: str,
        message: str,
        code: str = "PIPELINE_FAILURE",
    ) -> Diagnostic:
        by_file = {slice_.file_path: slice_ for slice_ in context_slices}
        for file_path in touched_files:
            if file_path in by_file:
                excerpt = by_file[file_path].excerpt.splitlines()
                return Diagnostic(
                    level="error",
                    code=code,
                    message=message,
                    pass_name=pass_name,
                    file_path=file_path,
                    line=1 if excerpt else None,
                    details={"rationale": by_file[file_path].rationale},
                )
        return Diagnostic(level="error", code=code, message=message, pass_name=pass_name)


class TaskSummaryWriter:
    """Writes a compact machine-readable task manifest."""

    def __init__(self, summary_path: str | Path) -> None:
        self.summary_path = Path(summary_path)
        self.summary_path.parent.mkdir(parents=True, exist_ok=True)

    def write(self, payload: dict[str, Any]) -> None:
        self.summary_path.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8")
