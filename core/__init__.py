"""Core runtime primitives for the compiler-oriented execution pipeline."""

from .action_cache import ActionCache, CachedAction
from .adapters import DockerRuntimeAdapter, LocalRuntimeAdapter, RuntimeAdapter, RuntimeSession
from .diagnostics import Diagnostic, SourceMapper, TaskSummaryWriter
from .dispatcher import TieredDispatcher
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
from .exceptions import BudgetExceeded, PipelineFailure, SecurityViolation, VerificationFailure, WorktreeError
from .ir import (
    ContextSlice,
    ExecutionPlan,
    FailToPassContract,
    FrontendIR,
    LinkedSymbol,
    MetricThresholdContract,
    MiddleEndIR,
    ModelTier,
    PassToPassContract,
    PytestSelector,
    ResourceConstraints,
    ResourceLimits,
    SandboxType,
    SymbolDefinition,
    VerificationContract,
)
from .linker import Linker
from .monitor import RuntimeMonitor, run_with_monitor
from .optimizer_cache import OptimizerCache
from .pipeline import PassManager, Pipeline, PipelineRequest, PipelineRunResult
from .refinement import RefinementEmitter, RefinementPlanner, RefinementTask
from .saga import Saga
from .slicing import ContextPruner
from .symbols import SymbolTableBuilder
from .telemetry import CostTracker
from .verifier import VerificationRunner
from .vcs import StablePoint, VCSAdapter
from .watcher import AuthorizedWriteWatcher
from .worktree import WorktreeManager

__all__ = [
    "ActionCache",
    "DockerRuntimeAdapter",
    "Diagnostic",
    "CachedAction",
    "BaseModelExecutor",
    "build_executor",
    "BudgetExceeded",
    "ContextPruner",
    "ContextSlice",
    "EventStore",
    "ClaudeCodeExecutor",
    "ExecutorConfig",
    "ExecutionPlan",
    "ExecutionResult",
    "LocalRuntimeAdapter",
    "FailToPassContract",
    "FrontendIR",
    "LinkedSymbol",
    "MetricThresholdContract",
    "ModelExecutionError",
    "ModelProvider",
    "ModelTier",
    "MiddleEndIR",
    "OpenAICompatibleExecutor",
    "OpenClawExecutor",
    "OptimizerCache",
    "PassManager",
    "Pipeline",
    "PipelineFailure",
    "PipelineRequest",
    "PipelineRunResult",
    "PassToPassContract",
    "PytestSelector",
    "RefinementEmitter",
    "RefinementPlanner",
    "RefinementTask",
    "ResourceConstraints",
    "ResourceLimits",
    "SourceMapper",
    "RuntimeMonitor",
    "RuntimeAdapter",
    "RuntimeSession",
    "run_with_monitor",
    "Saga",
    "SandboxType",
    "SymbolDefinition",
    "SymbolTableBuilder",
    "Linker",
    "SecurityViolation",
    "StablePoint",
    "VerificationFailure",
    "VerificationContract",
    "VerificationRunner",
    "VCSAdapter",
    "AuthorizedWriteWatcher",
    "CostTracker",
    "TieredDispatcher",
    "TaskSummaryWriter",
    "WorktreeError",
    "WorktreeManager",
]
