"""Shared execution result types."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any


@dataclass(frozen=True)
class ExecutionResult:
    patch: str
    touched_files: list[str]
    metadata: dict[str, Any] = field(default_factory=dict)
