"""Verification runner for contract-based compiler checks."""

from __future__ import annotations

import os
import shutil
import subprocess
import asyncio
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Awaitable, Protocol

from .exceptions import VerificationFailure
from .ir import (
    FailToPassContract,
    MetricThresholdContract,
    MiddleEndIR,
    PassToPassContract,
    VerificationContract,
)


class MetricsProvider(Protocol):
    def __call__(self, metric_name: str, repo_root: Path) -> float: ...


class AsyncCommandRunner(Protocol):
    def __call__(self, command: list[str], cwd: str | Path) -> Awaitable["CommandResult"]: ...


@dataclass(frozen=True)
class CommandResult:
    command: list[str]
    exit_code: int
    stdout: str
    stderr: str


@dataclass(frozen=True)
class VerificationEvidence:
    stage: str
    contract_kind: str
    selector: str
    command: list[str]
    exit_code: int
    stdout: str
    stderr: str

    def model_dump(self) -> dict[str, Any]:
        return {
            "stage": self.stage,
            "contract_kind": self.contract_kind,
            "selector": self.selector,
            "command": self.command,
            "exit_code": self.exit_code,
            "stdout": self.stdout,
            "stderr": self.stderr,
        }


class VerificationRunner:
    """Executes compiler verification contracts against a repository state."""

    def __init__(self, *, metrics_provider: MetricsProvider | None = None) -> None:
        self.metrics_provider = metrics_provider

    def run_pre_patch(self, ir: MiddleEndIR, repo_root: str | Path) -> list[VerificationEvidence]:
        evidence: list[VerificationEvidence] = []
        repo_path = Path(repo_root)
        for contract in ir.verification_contracts:
            if isinstance(contract, FailToPassContract):
                evidence.extend(self._run_fail_to_pass(contract, repo_path))
        return evidence

    def run_post_patch(self, ir: MiddleEndIR, repo_root: str | Path) -> list[VerificationEvidence]:
        evidence: list[VerificationEvidence] = []
        repo_path = Path(repo_root)
        for contract in ir.verification_contracts:
            if isinstance(contract, PassToPassContract):
                evidence.extend(self._run_pass_to_pass(contract, repo_path))
            elif isinstance(contract, MetricThresholdContract):
                evidence.append(self._run_metric(contract, repo_path))
        return evidence

    async def run_pre_patch_async(
        self,
        ir: MiddleEndIR,
        repo_root: str | Path,
        *,
        command_runner: AsyncCommandRunner,
    ) -> list[VerificationEvidence]:
        evidence: list[VerificationEvidence] = []
        repo_path = Path(str(repo_root))
        for contract in ir.verification_contracts:
            if isinstance(contract, FailToPassContract):
                evidence.extend(await self._run_fail_to_pass_async(contract, repo_path, command_runner))
        return evidence

    async def run_post_patch_async(
        self,
        ir: MiddleEndIR,
        repo_root: str | Path,
        *,
        command_runner: AsyncCommandRunner,
    ) -> list[VerificationEvidence]:
        evidence: list[VerificationEvidence] = []
        repo_path = Path(str(repo_root))
        for contract in ir.verification_contracts:
            if isinstance(contract, PassToPassContract):
                evidence.extend(await self._run_pass_to_pass_async(contract, repo_path, command_runner))
            elif isinstance(contract, MetricThresholdContract):
                evidence.append(self._run_metric(contract, repo_path))
        return evidence

    def summarize(
        self,
        *,
        pre_patch: list[VerificationEvidence],
        post_patch: list[VerificationEvidence],
    ) -> dict[str, Any]:
        return {
            "pre_patch": [item.model_dump() for item in pre_patch],
            "post_patch": [item.model_dump() for item in post_patch],
            "status": "verified",
        }

    def _run_fail_to_pass(self, contract: FailToPassContract, repo_root: Path) -> list[VerificationEvidence]:
        evidence: list[VerificationEvidence] = []
        for selector in contract.selectors:
            result = self._run_pytest(selector.selector, repo_root)
            if result.exit_code == 0:
                raise VerificationFailure(
                    f"fail-to-pass selector unexpectedly passed before patch: {selector.selector}"
                )
            evidence.append(result)
        return evidence

    async def _run_fail_to_pass_async(
        self,
        contract: FailToPassContract,
        repo_root: Path,
        command_runner: AsyncCommandRunner,
    ) -> list[VerificationEvidence]:
        evidence: list[VerificationEvidence] = []
        for selector in contract.selectors:
            result = await self._run_pytest_async(selector.selector, repo_root, command_runner)
            if result.exit_code == 0:
                raise VerificationFailure(
                    f"fail-to-pass selector unexpectedly passed before patch: {selector.selector}"
                )
            evidence.append(result)
        return evidence

    def _run_pass_to_pass(self, contract: PassToPassContract, repo_root: Path) -> list[VerificationEvidence]:
        evidence: list[VerificationEvidence] = []
        for selector in contract.selectors:
            retries = contract.allow_flaky_retries + 1
            last_result: VerificationEvidence | None = None
            for _ in range(retries):
                last_result = self._run_pytest(selector.selector, repo_root)
                if last_result.exit_code == 0:
                    break
            assert last_result is not None
            if last_result.exit_code != 0:
                raise VerificationFailure(f"pass-to-pass selector failed after patch: {selector.selector}")
            evidence.append(last_result)
        return evidence

    async def _run_pass_to_pass_async(
        self,
        contract: PassToPassContract,
        repo_root: Path,
        command_runner: AsyncCommandRunner,
    ) -> list[VerificationEvidence]:
        evidence: list[VerificationEvidence] = []
        for selector in contract.selectors:
            retries = contract.allow_flaky_retries + 1
            last_result: VerificationEvidence | None = None
            for _ in range(retries):
                last_result = await self._run_pytest_async(selector.selector, repo_root, command_runner)
                if last_result.exit_code == 0:
                    break
            assert last_result is not None
            if last_result.exit_code != 0:
                raise VerificationFailure(f"pass-to-pass selector failed after patch: {selector.selector}")
            evidence.append(last_result)
        return evidence

    def _run_metric(self, contract: MetricThresholdContract, repo_root: Path) -> VerificationEvidence:
        if self.metrics_provider is None:
            raise VerificationFailure(f"no metrics provider configured for metric {contract.metric_name}")
        value = self.metrics_provider(contract.metric_name, repo_root)
        if contract.minimum is not None and value < contract.minimum:
            raise VerificationFailure(f"metric {contract.metric_name} below minimum: {value} < {contract.minimum}")
        if contract.maximum is not None and value > contract.maximum:
            raise VerificationFailure(f"metric {contract.metric_name} above maximum: {value} > {contract.maximum}")
        return VerificationEvidence(
            stage="post_patch",
            contract_kind=contract.kind,
            selector=contract.metric_name,
            command=["metric", contract.metric_name],
            exit_code=0,
            stdout=str(value),
            stderr="",
        )

    def _run_pytest(self, selector: str, repo_root: Path) -> VerificationEvidence:
        pytest_binary = shutil.which("pytest")
        if pytest_binary is None:
            raise VerificationFailure("pytest is required for verification contracts but is not installed")
        for cache_dir in repo_root.rglob("__pycache__"):
            shutil.rmtree(cache_dir, ignore_errors=True)
        command = [pytest_binary, selector]
        env = os.environ.copy()
        env["PYTHONDONTWRITEBYTECODE"] = "1"
        result = subprocess.run(command, cwd=repo_root, env=env, capture_output=True, text=True, check=False)
        return VerificationEvidence(
            stage="pre_or_post_patch",
            contract_kind="pytest",
            selector=selector,
            command=command,
            exit_code=result.returncode,
            stdout=result.stdout,
            stderr=result.stderr,
        )

    async def _run_pytest_async(
        self,
        selector: str,
        repo_root: Path,
        command_runner: AsyncCommandRunner,
    ) -> VerificationEvidence:
        pytest_binary = shutil.which("pytest") or "pytest"
        command = [pytest_binary, selector]
        result = await command_runner(command, repo_root)
        return VerificationEvidence(
            stage="pre_or_post_patch",
            contract_kind="pytest",
            selector=selector,
            command=result.command,
            exit_code=result.exit_code,
            stdout=result.stdout,
            stderr=result.stderr,
        )
