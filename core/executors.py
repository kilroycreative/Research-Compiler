"""Model-backed execution adapters for compiler pipeline patch generation."""

from __future__ import annotations

import json
import os
import re
import subprocess
from dataclasses import dataclass
from enum import StrEnum
from pathlib import Path
from urllib import error, request

from pydantic import BaseModel, ConfigDict, Field

from .execution_types import ExecutionResult
from .exceptions import PipelineFailure
from .ir import ExecutionPlan


class ModelProvider(StrEnum):
    CODEX = "codex"
    CLAUDE_CODE = "claude_code"
    OPENCLAW = "openclaw"
    LM_STUDIO = "lm_studio"


class ExecutorConfig(BaseModel):
    model_config = ConfigDict(extra="forbid")

    provider: ModelProvider
    model: str | None = None
    command: str | None = None
    base_url: str | None = None
    api_key_env: str | None = None
    timeout_seconds: int = Field(default=600, gt=0)
    extra_args: list[str] = Field(default_factory=list)


@dataclass(frozen=True)
class PreparedPrompt:
    system_prompt: str
    user_prompt: str


class ModelExecutionError(PipelineFailure):
    """Raised when a model-backed executor cannot produce a valid patch."""


class PromptCompiler:
    """Builds a deterministic prompt that asks a model for a unified diff only."""

    def build(self, plan: ExecutionPlan, workspace: Path) -> PreparedPrompt:
        file_sections: list[str] = []
        for rel_path in plan.authorized_files:
            file_path = workspace / rel_path
            if file_path.exists():
                file_sections.append(f"FILE: {rel_path}\n```text\n{file_path.read_text(encoding='utf-8')}\n```")
            else:
                file_sections.append(f"FILE: {rel_path}\n<missing>")

        system_prompt = (
            "You are a software patch generator. "
            "Return only a unified git diff. "
            "Do not include prose or markdown outside the diff."
        )
        user_prompt = "\n\n".join(
            [
                f"Task ID: {plan.task_id}",
                f"Base commit: {plan.base_commit}",
                "Constitution:",
                plan.constitution,
                "Authorized files:",
                "\n".join(f"- {path}" for path in plan.authorized_files),
                "Resource limits:",
                json.dumps(plan.resource_limits.model_dump(mode="json"), sort_keys=True),
                "Requirements:",
                "- Output a valid unified git diff beginning with `diff --git`.",
                "- Touch only the authorized files.",
                "- If no safe patch is possible, return an empty response.",
                "Workspace snapshot:",
                "\n\n".join(file_sections),
            ]
        )
        return PreparedPrompt(system_prompt=system_prompt, user_prompt=user_prompt)


class BaseModelExecutor:
    def __init__(self, config: ExecutorConfig, *, prompt_compiler: PromptCompiler | None = None) -> None:
        self.config = config
        self.prompt_compiler = prompt_compiler or PromptCompiler()

    async def execute(self, plan: ExecutionPlan, workspace: Path) -> ExecutionResult:
        prompt = self.prompt_compiler.build(plan, workspace)
        raw_output = await self._run(prompt, workspace)
        patch = extract_unified_diff(raw_output)
        return ExecutionResult(
            patch=patch,
            touched_files=extract_patch_paths(patch),
            metadata={"provider": self.config.provider, "model": self.config.model},
        )

    async def _run(self, prompt: PreparedPrompt, workspace: Path) -> str:
        raise NotImplementedError


class ClaudeCodeExecutor(BaseModelExecutor):
    async def _run(self, prompt: PreparedPrompt, workspace: Path) -> str:
        command = [
            self.config.command or "claude",
            "-p",
            "--output-format",
            "text",
            "--permission-mode",
            "bypassPermissions",
            "--append-system-prompt",
            prompt.system_prompt,
            "--model",
            self.config.model or "sonnet",
            *self.config.extra_args,
            prompt.user_prompt,
        ]
        return run_subprocess(command, cwd=workspace, timeout_seconds=self.config.timeout_seconds)


class OpenClawExecutor(BaseModelExecutor):
    async def _run(self, prompt: PreparedPrompt, workspace: Path) -> str:
        command = [
            self.config.command or "openclaw",
            "agent",
            "--model",
            self.config.model or "claude-cli/opus-4.6",
            "--message",
            f"{prompt.system_prompt}\n\n{prompt.user_prompt}",
            *self.config.extra_args,
        ]
        return run_subprocess(command, cwd=workspace, timeout_seconds=self.config.timeout_seconds)


class OpenAICompatibleExecutor(BaseModelExecutor):
    def __init__(self, config: ExecutorConfig, *, default_base_url: str, default_api_key_env: str) -> None:
        super().__init__(config)
        self.default_base_url = default_base_url.rstrip("/")
        self.default_api_key_env = default_api_key_env

    async def _run(self, prompt: PreparedPrompt, workspace: Path) -> str:
        del workspace
        url = f"{(self.config.base_url or self.default_base_url).rstrip('/')}/responses"
        model = self.config.model or self._default_model()
        api_key_env = self.config.api_key_env or self.default_api_key_env
        api_key = os.environ.get(api_key_env, "")
        headers = {"Content-Type": "application/json"}
        if api_key:
            headers["Authorization"] = f"Bearer {api_key}"
        elif self.config.provider == ModelProvider.CODEX:
            raise ModelExecutionError(f"missing API key in environment variable {api_key_env}")

        payload = {
            "model": model,
            "input": [
                {"role": "system", "content": [{"type": "input_text", "text": prompt.system_prompt}]},
                {"role": "user", "content": [{"type": "input_text", "text": prompt.user_prompt}]},
            ],
        }
        req = request.Request(
            url,
            data=json.dumps(payload).encode("utf-8"),
            headers=headers,
            method="POST",
        )
        try:
            with request.urlopen(req, timeout=self.config.timeout_seconds) as response:
                return parse_openai_compatible_output(response.read().decode("utf-8"))
        except error.HTTPError as exc:
            detail = exc.read().decode("utf-8", errors="replace")
            raise ModelExecutionError(f"{self.config.provider} request failed: {exc.code} {detail}") from exc
        except error.URLError as exc:
            raise ModelExecutionError(f"{self.config.provider} request failed: {exc.reason}") from exc

    def _default_model(self) -> str:
        if self.config.provider == ModelProvider.CODEX:
            return "gpt-5"
        if self.config.provider == ModelProvider.LM_STUDIO:
            return "local-model"
        raise ModelExecutionError(f"no default model for provider {self.config.provider}")


def build_executor(config: ExecutorConfig) -> BaseModelExecutor:
    if config.provider == ModelProvider.CLAUDE_CODE:
        return ClaudeCodeExecutor(config)
    if config.provider == ModelProvider.OPENCLAW:
        return OpenClawExecutor(config)
    if config.provider == ModelProvider.CODEX:
        return OpenAICompatibleExecutor(
            config,
            default_base_url="https://api.openai.com/v1",
            default_api_key_env="OPENAI_API_KEY",
        )
    if config.provider == ModelProvider.LM_STUDIO:
        return OpenAICompatibleExecutor(
            config,
            default_base_url="http://localhost:1234/v1",
            default_api_key_env="LM_STUDIO_API_KEY",
        )
    raise ModelExecutionError(f"unsupported provider: {config.provider}")


def run_subprocess(command: list[str], *, cwd: Path, timeout_seconds: int) -> str:
    try:
        result = subprocess.run(
            command,
            cwd=cwd,
            capture_output=True,
            text=True,
            timeout=timeout_seconds,
            check=False,
        )
    except FileNotFoundError as exc:
        raise ModelExecutionError(f"command not found: {command[0]}") from exc
    except subprocess.TimeoutExpired as exc:
        raise ModelExecutionError(f"command timed out: {command[0]}") from exc
    if result.returncode != 0:
        raise ModelExecutionError(f"command failed ({result.returncode}): {command[0]}\n{result.stderr.strip()}")
    return result.stdout


def parse_openai_compatible_output(body: str) -> str:
    payload = json.loads(body)
    if isinstance(payload.get("output_text"), str) and payload["output_text"].strip():
        return payload["output_text"]
    text_parts: list[str] = []
    for item in payload.get("output", []):
        for content in item.get("content", []):
            if content.get("type") in {"output_text", "text"} and content.get("text"):
                text_parts.append(content["text"])
    if text_parts:
        return "\n".join(text_parts)
    raise ModelExecutionError("model response did not include text output")


def extract_unified_diff(text: str) -> str:
    fenced = re.search(r"```(?:diff)?\n(.*?)```", text, flags=re.DOTALL)
    candidate = fenced.group(1) if fenced else text
    match = re.search(r"(?ms)^diff --git .*", candidate)
    if match:
        return match.group(0).strip() + "\n"
    if not candidate.strip():
        return ""
    raise ModelExecutionError("model output did not contain a unified diff")


def extract_patch_paths(patch: str) -> list[str]:
    paths: list[str] = []
    for line in patch.splitlines():
        if line.startswith("+++ b/"):
            value = line.removeprefix("+++ b/").strip()
            if value != "/dev/null":
                paths.append(value)
    return sorted(set(paths))
