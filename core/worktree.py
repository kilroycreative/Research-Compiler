"""Content-addressed git worktree management for experiment isolation."""

from __future__ import annotations

import subprocess
from hashlib import sha256
from pathlib import Path

from .exceptions import WorktreeError


class WorktreeManager:
    """Creates and cleans up deterministic git worktree paths."""

    def __init__(self, repo_root: str | Path, worktree_root: str | Path | None = None) -> None:
        self.repo_root = Path(repo_root).resolve()
        default_root = self.repo_root / ".deep-loop" / "worktrees"
        self.worktree_root = Path(worktree_root).resolve() if worktree_root else default_root
        self.worktree_root.mkdir(parents=True, exist_ok=True)

    def hashed_path(self, *, task_id: str, base_commit: str, constitution: str) -> Path:
        digest = sha256(f"{task_id}:{base_commit}:{constitution}".encode("utf-8")).hexdigest()[:16]
        return self.worktree_root / f"{task_id}-{digest}"

    def create(self, *, task_id: str, base_commit: str, constitution: str) -> Path:
        self._ensure_git_repo()
        target = self.hashed_path(task_id=task_id, base_commit=base_commit, constitution=constitution)
        if target.exists():
            return target
        result = subprocess.run(
            ["git", "worktree", "add", "--detach", str(target), base_commit],
            cwd=self.repo_root,
            capture_output=True,
            text=True,
            check=False,
        )
        if result.returncode != 0:
            raise WorktreeError(result.stderr.strip() or f"failed to create worktree at {target}")
        return target

    def cleanup(self, path: str | Path) -> None:
        target = Path(path).resolve()
        if not target.exists():
            return
        result = subprocess.run(
            ["git", "worktree", "remove", "--force", str(target)],
            cwd=self.repo_root,
            capture_output=True,
            text=True,
            check=False,
        )
        if result.returncode != 0:
            raise WorktreeError(result.stderr.strip() or f"failed to remove worktree at {target}")

    def _ensure_git_repo(self) -> None:
        if not (self.repo_root / ".git").exists():
            raise WorktreeError(f"{self.repo_root} is not a git repository")
