"""Core runtime primitives for the compiler-oriented execution pipeline."""

from .action_cache import ActionCache, CachedAction
from .events import EventStore
from .execution_types import ExecutionResult
from .executors import (
    BaseModelExecutor,
    ClaudeCodeExecutor,
    ExecutorConfig,
    ModelExecutionError,
    ModelProvider,
    OpenAICompatibleExecutor,
    OpenClawExecutor,
    build_executor,
)
from .exceptions import PipelineFailure, SecurityViolation, VerificationFailure, WorktreeError
from .ir import (
    ExecutionPlan,
    FailToPassContract,
    FrontendIR,
    MetricThresholdContract,
    MiddleEndIR,
    PassToPassContract,
    PytestSelector,
    ResourceLimits,
    SandboxType,
    VerificationContract,
)
from .pipeline import PassManager, Pipeline, PipelineRequest, PipelineRunResult
from .saga import Saga
from .verifier import VerificationRunner
from .watcher import AuthorizedWriteWatcher
from .worktree import WorktreeManager

__all__ = [
    "ActionCache",
    "CachedAction",
    "BaseModelExecutor",
    "build_executor",
    "EventStore",
    "ClaudeCodeExecutor",
    "ExecutorConfig",
    "ExecutionPlan",
    "ExecutionResult",
    "FailToPassContract",
    "FrontendIR",
    "MetricThresholdContract",
    "ModelExecutionError",
    "ModelProvider",
    "MiddleEndIR",
    "OpenAICompatibleExecutor",
    "OpenClawExecutor",
    "PassManager",
    "Pipeline",
    "PipelineFailure",
    "PipelineRequest",
    "PipelineRunResult",
    "PassToPassContract",
    "PytestSelector",
    "ResourceLimits",
    "Saga",
    "SandboxType",
    "SecurityViolation",
    "VerificationFailure",
    "VerificationContract",
    "VerificationRunner",
    "AuthorizedWriteWatcher",
    "WorktreeError",
    "WorktreeManager",
]
