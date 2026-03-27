"""Runtime filesystem monitor backends."""

from __future__ import annotations

import asyncio
import sys
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


class NativeLinuxMonitorBackend(MonitorBackend):
    name = "inotify"

    def __init__(self, timeout_ms: int = 1000) -> None:
        try:
            from inotify_simple import INotify, flags  # type: ignore
        except Exception as exc:
            raise RuntimeError("inotify backend unavailable") from exc
        self._INotify = INotify
        self._flags = flags
        self.timeout_ms = timeout_ms

    async def stream(self, workspace: Path, *, details: dict | None = None) -> AsyncIterator[RuntimeEvent]:
        inotify = self._INotify()
        watch_flags = (
            self._flags.CLOSE_WRITE
            | self._flags.MODIFY
            | self._flags.MOVED_TO
            | self._flags.CREATE
            | self._flags.DELETE
        )
        watches: dict[int, Path] = {}
        for directory in [workspace, *[path for path in workspace.rglob("*") if path.is_dir()]]:
            watches[inotify.add_watch(str(directory), watch_flags)] = directory
        try:
            while True:
                events = await asyncio.to_thread(inotify.read, self.timeout_ms)
                for event in events:
                    directory = watches.get(event.wd, workspace)
                    name = getattr(event, "name", "") or ""
                    changed_path = directory / name if name else directory
                    if changed_path.is_dir() and event.mask & self._flags.CREATE:
                        watches[inotify.add_watch(str(changed_path), watch_flags)] = changed_path
                        continue
                    if changed_path.is_dir():
                        continue
                    action = self._action_for_mask(event.mask)
                    if action is None:
                        continue
                    yield RuntimeEvent(
                        path=changed_path.relative_to(workspace).as_posix(),
                        action=action,
                        timestamp=time.time(),
                        details=details or {},
                    )
        finally:
            try:
                inotify.close()
            except Exception:
                pass

    def _action_for_mask(self, mask: int) -> str | None:
        if mask & self._flags.DELETE:
            return "deleted"
        if mask & self._flags.CREATE:
            return "created"
        if mask & self._flags.MOVED_TO:
            return "moved"
        if mask & self._flags.CLOSE_WRITE or mask & self._flags.MODIFY:
            return "modified"
        return None


class MacOSFSEventsMonitorBackend(MonitorBackend):
    name = "fsevents"

    def __init__(self) -> None:
        try:
            from watchdog.events import FileSystemEventHandler  # type: ignore
            from watchdog.observers import Observer  # type: ignore
        except Exception as exc:
            raise RuntimeError("macOS watchdog backend unavailable") from exc
        self._FileSystemEventHandler = FileSystemEventHandler
        self._Observer = Observer

    async def stream(self, workspace: Path, *, details: dict | None = None) -> AsyncIterator[RuntimeEvent]:
        queue: asyncio.Queue[RuntimeEvent] = asyncio.Queue()
        loop = asyncio.get_running_loop()

        class Handler(self._FileSystemEventHandler):
            def dispatch(inner_self, event) -> None:  # type: ignore[override]
                if getattr(event, "is_directory", False):
                    return
                event_type = getattr(event, "event_type", "modified")
                src_path = Path(getattr(event, "dest_path", None) or event.src_path)
                runtime_event = RuntimeEvent(
                    path=src_path.relative_to(workspace).as_posix(),
                    action=event_type,
                    timestamp=time.time(),
                    details=details or {},
                )
                loop.call_soon_threadsafe(queue.put_nowait, runtime_event)

        observer = self._Observer()
        handler = Handler()
        observer.schedule(handler, str(workspace), recursive=True)
        observer.start()
        try:
            while True:
                yield await queue.get()
        finally:
            observer.stop()
            observer.join(timeout=1)


def build_monitor_backend(preferred: str = "auto") -> MonitorBackend:
    if preferred == "polling":
        return PollingMonitorBackend()
    if preferred == "watchfiles":
        return WatchfilesMonitorBackend()
    if preferred == "linux-native":
        return NativeLinuxMonitorBackend()
    if preferred == "macos-fsevents":
        return MacOSFSEventsMonitorBackend()

    if sys.platform.startswith("linux"):
        try:
            return NativeLinuxMonitorBackend()
        except RuntimeError:
            pass
    if sys.platform == "darwin":
        try:
            return MacOSFSEventsMonitorBackend()
        except RuntimeError:
            pass
    try:
        return WatchfilesMonitorBackend()
    except RuntimeError:
        return PollingMonitorBackend()
