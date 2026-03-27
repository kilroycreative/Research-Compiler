"""Core runtime primitives for the compiler-oriented execution pipeline."""

from .action_cache import ActionCache, CachedAction
from .adapters import (
    DockerRuntimeAdapter,
    E2BSandboxProvider,
    GenericRemoteRuntimeAdapter,
    HumanLayerRuntimeAdapter,
    LocalRuntimeAdapter,
    ModalSandboxProvider,
    RemoteSandboxHandle,
    RemoteSandboxProvider,
    RuntimeAdapter,
    RuntimeSession,
)
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
from .monitor_backends import (
    MacOSFSEventsMonitorBackend,
    MonitorBackend,
    NativeLinuxMonitorBackend,
    PollingMonitorBackend,
    WatchfilesMonitorBackend,
    build_monitor_backend,
)
from .merge_queue import MergeQueue, QueueResult, QueueTask
from .optimizer_cache import OptimizerCache
from .optimizers.tree_sitter_adapter import LanguagePack, TreeSitterAdapter
from .parser_types import ParsedDefinition, ParsedImport, ParsedModule
from .parsers import ParserRegistry
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
    "E2BSandboxProvider",
    "Diagnostic",
    "CachedAction",
    "GenericRemoteRuntimeAdapter",
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
    "MacOSFSEventsMonitorBackend",
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
    "ParsedImport",
    "ParsedModule",
    "PassManager",
    "ParserRegistry",
    "Pipeline",
    "PipelineFailure",
    "PipelineRequest",
    "PipelineRunResult",
    "PassToPassContract",
    "PytestSelector",
    "RemoteSandboxHandle",
    "RemoteSandboxProvider",
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
    "NativeLinuxMonitorBackend",
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
    "ModalSandboxProvider",
    "TreeSitterAdapter",
    "WatchfilesMonitorBackend",
    "WorktreeError",
    "WorktreeManager",
    "LanguagePack",
    "build_monitor_backend",
]
