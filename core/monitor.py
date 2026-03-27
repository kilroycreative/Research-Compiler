"""Live runtime monitor and Andon enforcement."""

from __future__ import annotations

import asyncio
from collections.abc import Awaitable, Callable

from .adapters import RuntimeAdapter, RuntimeEvent, RuntimeSession
from .exceptions import SecurityViolation
from .watcher import AuthorizedWriteWatcher


class RuntimeMonitor:
    """Consumes runtime events and raises on unauthorized writes."""

    def __init__(self, watcher: AuthorizedWriteWatcher) -> None:
        self.watcher = watcher

    async def watch(
        self,
        runtime_adapter: RuntimeAdapter,
        session: RuntimeSession,
        on_event: Callable[[RuntimeEvent], Awaitable[None]] | None = None,
    ) -> None:
        async for event in runtime_adapter.stream_events(session):
            if on_event is not None:
                await on_event(event)
            self.watcher.validate_path(event.path)


async def run_with_monitor(
    executor_coro,
    *,
    monitor: RuntimeMonitor,
    runtime_adapter: RuntimeAdapter,
    session: RuntimeSession,
    on_event: Callable[[RuntimeEvent], Awaitable[None]] | None = None,
):
    execution_task = asyncio.create_task(executor_coro)
    monitor_task = asyncio.create_task(monitor.watch(runtime_adapter, session, on_event=on_event))
    done, pending = await asyncio.wait(
        {execution_task, monitor_task},
        return_when=asyncio.FIRST_COMPLETED,
    )
    if monitor_task in done and monitor_task.exception() is not None:
        execution_task.cancel()
        try:
            await execution_task
        except asyncio.CancelledError:
            pass
        raise monitor_task.exception()
    if execution_task in done and execution_task.exception() is not None:
        monitor_task.cancel()
        try:
            await monitor_task
        except asyncio.CancelledError:
            pass
        raise execution_task.exception()
    result = await execution_task
    monitor_task.cancel()
    try:
        await monitor_task
    except asyncio.CancelledError:
        pass
    return result
