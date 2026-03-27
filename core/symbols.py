"""Symbol indexing for the compiler middle-end."""

from __future__ import annotations

from pathlib import Path

from .parsers import ParserRegistry
from .ir import SymbolDefinition


class SymbolTableBuilder:
    """Builds a simple persistent-friendly symbol view for Python source files."""

    def __init__(self, parser_registry: ParserRegistry | None = None) -> None:
        self.parser_registry = parser_registry or ParserRegistry()

    def build(self, repo_root: str | Path, file_paths: list[str]) -> list[SymbolDefinition]:
        repo = Path(repo_root).resolve()
        parser_registry = getattr(self, "parser_registry", None) or ParserRegistry()
        self.parser_registry = parser_registry
        symbols: list[SymbolDefinition] = []
        for rel_path in sorted(set(file_paths)):
            file_path = repo / rel_path
            if not file_path.exists():
                continue
            source = file_path.read_text(encoding="utf-8")
            module = parser_registry.parse_file(file_path, source)
            symbols.extend(
                SymbolDefinition(
                    name=definition.name,
                    kind=self._normalize_kind(definition.kind),
                    file_path=rel_path,
                    start_line=definition.start_line,
                    end_line=definition.end_line,
                    signature=definition.signature,
                    exported=definition.exported,
                )
                for definition in module.definitions
            )
        return symbols

    def _normalize_kind(self, kind: str) -> str:
        if kind in {"function", "class", "method", "assignment", "import"}:
            return kind
        return "class" if kind in {"interface", "type", "struct", "enum", "trait"} else "assignment"
