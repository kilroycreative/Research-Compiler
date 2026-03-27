"""Core runtime primitives for the compiler-oriented execution pipeline."""

from .action_cache import ActionCache, CachedAction
from .adapters import DockerRuntimeAdapter, HumanLayerRuntimeAdapter, LocalRuntimeAdapter, RuntimeAdapter, RuntimeSession
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
from .monitor_backends import MonitorBackend, PollingMonitorBackend, WatchfilesMonitorBackend, build_monitor_backend
from .merge_queue import MergeQueue, QueueResult, QueueTask
from .optimizer_cache import OptimizerCache
from .parsers import ParsedDefinition, ParsedModule, ParserRegistry
from .pipeline import PassManager, Pipeline, PipelineRequest, PipelineRunResult
from .refinement import RefinementEmitter, RefinementPlanner, RefinementQueueEmitter, RefinementTask
from .refinement_runner import RefinementQueueRunner
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
    "HumanLayerRuntimeAdapter",
    "LocalRuntimeAdapter",
    "FailToPassContract",
    "FrontendIR",
    "LinkedSymbol",
    "MergeQueue",
    "MetricThresholdContract",
    "MonitorBackend",
    "ModelExecutionError",
    "ModelProvider",
    "ModelTier",
    "MiddleEndIR",
    "OpenAICompatibleExecutor",
    "OpenClawExecutor",
    "OptimizerCache",
    "ParsedDefinition",
    "ParsedModule",
    "PassManager",
    "ParserRegistry",
    "Pipeline",
    "PipelineFailure",
    "PipelineRequest",
    "PipelineRunResult",
    "PassToPassContract",
    "PytestSelector",
    "PollingMonitorBackend",
    "QueueResult",
    "QueueTask",
    "RefinementEmitter",
    "RefinementPlanner",
    "RefinementQueueEmitter",
    "RefinementQueueRunner",
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
    "WatchfilesMonitorBackend",
    "WorktreeError",
    "WorktreeManager",
    "build_monitor_backend",
]
