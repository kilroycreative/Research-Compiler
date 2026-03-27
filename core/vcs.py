"""Version-control adapter for verified patch application and rollback."""

from __future__ import annotations

import subprocess
from dataclasses import dataclass
from pathlib import Path

from .exceptions import PipelineFailure


@dataclass(frozen=True)
class StablePoint:
    repo_root: Path
    commit: str


class VCSAdapter:
    """Wraps patch application, rollback, and commit promotion."""

    def snapshot_stable(self, repo_root: str | Path) -> StablePoint:
        root = Path(repo_root).resolve()
        commit = subprocess.run(
            ["git", "rev-parse", "HEAD"],
            cwd=root,
            capture_output=True,
            text=True,
            check=False,
        )
        if commit.returncode != 0:
            raise PipelineFailure(commit.stderr.strip() or "failed to snapshot stable commit")
        return StablePoint(repo_root=root, commit=commit.stdout.strip())

    def apply_patch(self, repo_root: str | Path, patch: str) -> None:
        root = Path(repo_root).resolve()
        if not patch.strip():
            return
        check = subprocess.run(
            ["git", "apply", "--check", "-"],
            cwd=root,
            input=patch,
            text=True,
            capture_output=True,
            check=False,
        )
        if check.returncode == 0:
            process = subprocess.run(
                ["git", "apply", "--whitespace=nowarn", "-"],
                cwd=root,
                input=patch,
                text=True,
                capture_output=True,
                check=False,
            )
            if process.returncode != 0:
                raise PipelineFailure(process.stderr.strip() or "failed to apply patch")
            return

        reverse = subprocess.run(
            ["git", "apply", "--reverse", "--check", "-"],
            cwd=root,
            input=patch,
            text=True,
            capture_output=True,
            check=False,
        )
        if reverse.returncode == 0:
            return
        raise PipelineFailure(check.stderr.strip() or "patch cannot be applied cleanly")

    def reverse_patch(self, repo_root: str | Path, patch: str) -> None:
        root = Path(repo_root).resolve()
        if not patch.strip():
            return
        process = subprocess.run(
            ["git", "apply", "--reverse", "--whitespace=nowarn", "-"],
            cwd=root,
            input=patch,
            text=True,
            capture_output=True,
            check=False,
        )
        if process.returncode != 0:
            raise PipelineFailure(process.stderr.strip() or "failed to reverse patch")

    def promote_commit(self, repo_root: str | Path, *, message: str) -> str:
        root = Path(repo_root).resolve()
        add = subprocess.run(["git", "add", "."], cwd=root, capture_output=True, text=True, check=False)
        if add.returncode != 0:
            raise PipelineFailure(add.stderr.strip() or "failed to stage changes")
        commit = subprocess.run(
            ["git", "commit", "-m", message],
            cwd=root,
            capture_output=True,
            text=True,
            check=False,
        )
        if commit.returncode != 0:
            raise PipelineFailure(commit.stderr.strip() or "failed to create commit")
        head = subprocess.run(
            ["git", "rev-parse", "HEAD"],
            cwd=root,
            capture_output=True,
            text=True,
            check=False,
        )
        if head.returncode != 0:
            raise PipelineFailure(head.stderr.strip() or "failed to resolve promoted commit")
        return head.stdout.strip()

    def revert_to_stable(self, stable_point: StablePoint) -> None:
        root = stable_point.repo_root
        clean = subprocess.run(
            ["git", "reset", "--hard", stable_point.commit],
            cwd=root,
            capture_output=True,
            text=True,
            check=False,
        )
        if clean.returncode != 0:
            raise PipelineFailure(clean.stderr.strip() or "failed to reset to stable commit")
        subprocess.run(
            ["git", "clean", "-fd"],
            cwd=root,
            capture_output=True,
            text=True,
            check=False,
        )
