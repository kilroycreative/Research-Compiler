"""Shared parser result types."""

from __future__ import annotations

from dataclasses import dataclass, field


@dataclass(frozen=True)
class ParsedImport:
    module: str
    imported_name: str | None = None
    alias: str | None = None
    statement: str | None = None


@dataclass(frozen=True)
class ParsedDefinition:
    name: str
    kind: str
    start_line: int
    end_line: int
    signature: str | None = None
    exported: bool = True
    excerpt: str | None = None


@dataclass(frozen=True)
class ParsedModule:
    language: str
    imports: list[str] = field(default_factory=list)
    import_entries: list[ParsedImport] = field(default_factory=list)
    definitions: list[ParsedDefinition] = field(default_factory=list)
    excerpt_blocks: list[str] = field(default_factory=list)
    raw_excerpt: str = ""
    has_errors: bool = False
