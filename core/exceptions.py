"""Runtime exceptions for compiler pipeline execution."""

from __future__ import annotations


class PipelineFailure(RuntimeError):
    """Base class for pipeline execution failures."""


class VerificationFailure(PipelineFailure):
    """Raised when verification evidence does not satisfy the contracts."""


class SecurityViolation(PipelineFailure):
    """Raised when execution touches files outside the authorized whitelist."""


class WorktreeError(PipelineFailure):
    """Raised when worktree orchestration fails."""
