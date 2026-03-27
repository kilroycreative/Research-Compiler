"""Runtime filesystem monitor backends."""

from __future__ import annotations

import asyncio
import time
from abc import ABC, abstractmethod
from collections.abc import AsyncIterator
from pathlib import Path

from .adapters.base import RuntimeEvent


class MonitorBackend(ABC):
    name: str

    @abstractmethod
    async def stream(self, workspace: Path, *, details: dict | None = None) -> AsyncIterator[RuntimeEvent]:
        raise NotImplementedError


class PollingMonitorBackend(MonitorBackend):
    name = "polling"

    def __init__(self, interval_seconds: float = 0.05) -> None:
        self.interval_seconds = interval_seconds

    async def stream(self, workspace: Path, *, details: dict | None = None) -> AsyncIterator[RuntimeEvent]:
        mtimes: dict[Path, int] = {}
        while True:
            for path in workspace.rglob("*"):
                if path.is_dir():
                    continue
                try:
                    stat = path.stat()
                except FileNotFoundError:
                    continue
                current = stat.st_mtime_ns
                previous = mtimes.get(path)
                mtimes[path] = current
                if previous is None:
                    continue
                if current != previous:
                    yield RuntimeEvent(
                        path=path.relative_to(workspace).as_posix(),
                        action="modified",
                        timestamp=time.time(),
                        details=details or {},
                    )
            await asyncio.sleep(self.interval_seconds)


class WatchfilesMonitorBackend(MonitorBackend):
    name = "watchfiles"

    def __init__(self) -> None:
        try:
            from watchfiles import Change, awatch  # type: ignore
        except Exception as exc:
            raise RuntimeError("watchfiles backend unavailable") from exc
        self._Change = Change
        self._awatch = awatch

    async def stream(self, workspace: Path, *, details: dict | None = None) -> AsyncIterator[RuntimeEvent]:
        async for changes in self._awatch(workspace):
            for change, file_path in changes:
                change_name = str(change)
                if hasattr(self._Change, "added") and change == self._Change.added:
                    change_name = "created"
                elif hasattr(self._Change, "modified") and change == self._Change.modified:
                    change_name = "modified"
                elif hasattr(self._Change, "deleted") and change == self._Change.deleted:
                    change_name = "deleted"
                yield RuntimeEvent(
                    path=Path(file_path).relative_to(workspace).as_posix(),
                    action=change_name,
                    timestamp=time.time(),
                    details=details or {},
                )


def build_monitor_backend(preferred: str = "auto") -> MonitorBackend:
    if preferred == "polling":
        return PollingMonitorBackend()
    if preferred == "watchfiles":
        return WatchfilesMonitorBackend()
    try:
        return WatchfilesMonitorBackend()
    except RuntimeError:
        return PollingMonitorBackend()
