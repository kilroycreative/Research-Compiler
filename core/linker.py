"""Link imported symbols to known definitions."""

from __future__ import annotations

from pathlib import Path

from .parsers import ParserRegistry
from .ir import LinkedSymbol, SymbolDefinition


class Linker:
    """Builds a linker map from imports to indexed symbols."""

    def __init__(self, parser_registry: ParserRegistry | None = None) -> None:
        self.parser_registry = parser_registry or ParserRegistry()

    def build(self, repo_root: str | Path, file_paths: list[str], symbol_table: list[SymbolDefinition]) -> list[LinkedSymbol]:
        repo = Path(repo_root).resolve()
        by_name: dict[str, list[SymbolDefinition]] = {}
        for symbol in symbol_table:
            by_name.setdefault(symbol.name.split(".")[-1], []).append(symbol)

        linked: list[LinkedSymbol] = []
        for rel_path in sorted(set(file_paths)):
            file_path = repo / rel_path
            if not file_path.exists():
                continue
            source = file_path.read_text(encoding="utf-8")
            module = self.parser_registry.parse_file(file_path, source)
            for entry in module.import_entries:
                symbol_name = entry.alias or entry.imported_name or entry.module.split("::")[-1].split(".")[-1].split("/")[-1]
                resolved = self._resolve(entry.module, entry.imported_name or symbol_name, by_name)
                linked.append(
                    LinkedSymbol(
                        symbol_name=symbol_name,
                        file_path=rel_path,
                        source_module=entry.module,
                        resolved_file_path=resolved.file_path if resolved else None,
                        resolved_symbol_name=resolved.name if resolved else None,
                    )
                )
        return linked

    def _resolve(
        self,
        module_name: str | None,
        symbol_name: str,
        by_name: dict[str, list[SymbolDefinition]],
    ) -> SymbolDefinition | None:
        candidates = by_name.get(symbol_name, [])
        if not candidates:
            return None
        if module_name is None:
            return candidates[0]
        dotted_module = (
            module_name.replace(".", "/")
            .replace("::", "/")
            .lstrip("./")
        )
        for candidate in candidates:
            normalized = candidate.file_path
            for suffix in [".py", ".ts", ".tsx", ".js", ".jsx", ".go", ".rs"]:
                if normalized.endswith(suffix):
                    normalized = normalized.removesuffix(suffix)
                    break
            if normalized.endswith(dotted_module):
                return candidate
        return candidates[0]
