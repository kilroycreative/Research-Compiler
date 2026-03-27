"""Saga primitives for compensating pipeline side effects."""

from __future__ import annotations

import asyncio
from collections.abc import Awaitable, Callable
from dataclasses import dataclass, field
from typing import Any


AsyncCallable = Callable[[], Awaitable[Any]]


@dataclass(slots=True)
class SagaStep:
    name: str
    compensate: AsyncCallable


@dataclass(slots=True)
class Saga:
    """Tracks side effects and compensates them in reverse order on failure."""

    _steps: list[SagaStep] = field(default_factory=list)

    def add_compensation(self, name: str, compensate: AsyncCallable) -> None:
        self._steps.append(SagaStep(name=name, compensate=compensate))

    async def compensate(self) -> list[str]:
        completed: list[str] = []
        while self._steps:
            step = self._steps.pop()
            await step.compensate()
            completed.append(step.name)
        return completed

    async def run(self, action: Callable[[], Awaitable[Any]], *, name: str, compensate: AsyncCallable) -> Any:
        result = await action()
        self.add_compensation(name, compensate)
        return result

    async def close(self) -> None:
        await self.compensate()

    async def __aenter__(self) -> "Saga":
        return self

    async def __aexit__(self, exc_type, exc, tb) -> None:
        if exc is not None:
            await self.compensate()


def ensure_async(callback: Callable[[], Any]) -> AsyncCallable:
    async def runner() -> Any:
        result = callback()
        if asyncio.iscoroutine(result):
            return await result
        return result

    return runner
