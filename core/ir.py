"""Structured intermediate representations for the factory compiler pipeline."""

from __future__ import annotations

from enum import StrEnum
from typing import Annotated, Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator


def _normalize_authorized_path(path: str) -> str:
    cleaned = path.strip()
    if not cleaned:
        raise ValueError("authorized file entries must be non-empty")
    if cleaned.startswith("/"):
        raise ValueError("authorized file entries must be repository-relative, not absolute")
    return cleaned.rstrip("/")


class StrictModel(BaseModel):
    """Base model that forbids unknown fields for deterministic lowering."""

    model_config = ConfigDict(extra="forbid", frozen=True)


class SandboxType(StrEnum):
    LOCAL = "local"
    CONTAINER = "container"
    FIREJAIL = "firejail"
    WORKTREE = "worktree"


class PytestSelector(StrictModel):
    selector: str = Field(min_length=1)
    description: str | None = None


class FailToPassContract(StrictModel):
    kind: Literal["fail_to_pass"] = "fail_to_pass"
    selectors: list[PytestSelector] = Field(min_length=1)


class PassToPassContract(StrictModel):
    kind: Literal["pass_to_pass"] = "pass_to_pass"
    selectors: list[PytestSelector] = Field(min_length=1)
    allow_flaky_retries: int = Field(default=0, ge=0, le=3)


class MetricThresholdContract(StrictModel):
    kind: Literal["metric_threshold"] = "metric_threshold"
    metric_name: str = Field(min_length=1)
    minimum: float | None = None
    maximum: float | None = None
    unit: str | None = None

    @field_validator("maximum")
    @classmethod
    def validate_bounds(cls, maximum: float | None, info) -> float | None:
        minimum = info.data.get("minimum")
        if minimum is None or maximum is None:
            return maximum
        if minimum > maximum:
            raise ValueError("minimum must be less than or equal to maximum")
        return maximum


VerificationContract = Annotated[
    FailToPassContract | PassToPassContract | MetricThresholdContract,
    Field(discriminator="kind"),
]


class FrontendIR(StrictModel):
    task_id: str = Field(min_length=1)
    base_commit: str = Field(min_length=7)
    authorized_files: list[str] = Field(min_length=1)

    @field_validator("authorized_files")
    @classmethod
    def normalize_authorized_files(cls, value: list[str]) -> list[str]:
        normalized = sorted({_normalize_authorized_path(path) for path in value})
        if not normalized:
            raise ValueError("authorized_files must contain at least one unique path")
        return normalized


class MiddleEndIR(FrontendIR):
    verification_contracts: list[VerificationContract] = Field(min_length=1)
    constitution: str = Field(min_length=1, description="Task-specific CLAUDE.md or equivalent context")


class ResourceLimits(StrictModel):
    max_runtime_seconds: int = Field(gt=0)
    max_memory_mb: int = Field(gt=0)
    max_cpu_count: int = Field(default=1, gt=0)
    max_patch_bytes: int = Field(default=1_000_000, gt=0)


class ExecutionPlan(MiddleEndIR):
    model_id: str = Field(min_length=1)
    sandbox_type: SandboxType
    resource_limits: ResourceLimits
