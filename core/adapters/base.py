"""Runtime adapter base interfaces."""

from __future__ import annotations

from abc import ABC, abstractmethod
from collections.abc import AsyncIterator
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from ..ir import ExecutionPlan


@dataclass(frozen=True)
class RuntimeSession:
    workspace: Path
    telemetry: dict[str, Any] = field(default_factory=dict)
    cleanup_token: str | None = None
    opaque_state: Any | None = field(default=None, compare=False, repr=False)


@dataclass(frozen=True)
class RuntimeEvent:
    path: str
    action: str
    timestamp: float | None = None
    details: dict[str, Any] = field(default_factory=dict)


class RuntimeAdapter(ABC):
    """Impure runtime boundary for isolated execution environments."""

    @abstractmethod
    async def execute(self, plan: ExecutionPlan) -> RuntimeSession:
        raise NotImplementedError

    @abstractmethod
    async def compensate(self, session: RuntimeSession) -> None:
        raise NotImplementedError

    @abstractmethod
    async def stream_events(self, session: RuntimeSession) -> AsyncIterator[RuntimeEvent]:
        raise NotImplementedError

    @abstractmethod
    def telemetry(self, session: RuntimeSession) -> dict[str, Any]:
        raise NotImplementedError
