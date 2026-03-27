"""Authorized file monitoring for the compiler pipeline."""

from __future__ import annotations

from pathlib import Path

from .exceptions import SecurityViolation


def _normalize_repo_relative(path: str) -> str:
    cleaned = path.replace("\\", "/").strip().lstrip("./")
    return cleaned.rstrip("/")


class AuthorizedWriteWatcher:
    """Validates file mutations against an authorized repository-relative whitelist."""

    def __init__(self, repo_root: str | Path, authorized_files: list[str]) -> None:
        self.repo_root = Path(repo_root).resolve()
        self.authorized_files = {_normalize_repo_relative(item) for item in authorized_files}

    def validate_path(self, path: str | Path) -> str:
        candidate = Path(path)
        resolved = candidate.resolve() if candidate.is_absolute() else (self.repo_root / candidate).resolve()
        try:
            relative = resolved.relative_to(self.repo_root).as_posix()
        except ValueError as exc:
            raise SecurityViolation(f"path escapes repository root: {path}") from exc
        normalized = _normalize_repo_relative(relative)
        if normalized not in self.authorized_files:
            raise SecurityViolation(f"unauthorized file write: {normalized}")
        return normalized

    def validate_paths(self, paths: list[str | Path]) -> list[str]:
        return [self.validate_path(path) for path in paths]
