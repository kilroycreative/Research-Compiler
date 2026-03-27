"""AST-aware context slicing for model prompts."""

from __future__ import annotations

from pathlib import Path

from .parsers import ParserRegistry
from .ir import ContextSlice, LinkedSymbol, SymbolDefinition


class ContextPruner:
    """Builds minimal file slices around imports and top-level symbols."""

    def __init__(self, parser_registry: ParserRegistry | None = None) -> None:
        self.parser_registry = parser_registry or ParserRegistry()

    def build(
        self,
        repo_root: str | Path,
        file_paths: list[str],
        symbol_table: list[SymbolDefinition],
        linker_map: list[LinkedSymbol],
    ) -> list[ContextSlice]:
        repo = Path(repo_root).resolve()
        symbols_by_file: dict[str, list[SymbolDefinition]] = {}
        for symbol in symbol_table:
            symbols_by_file.setdefault(symbol.file_path, []).append(symbol)

        links_by_file: dict[str, list[LinkedSymbol]] = {}
        for link in linker_map:
            links_by_file.setdefault(link.file_path, []).append(link)

        slices: list[ContextSlice] = []
        for rel_path in sorted(set(file_paths)):
            file_path = repo / rel_path
            if not file_path.exists():
                continue
            source = file_path.read_text(encoding="utf-8")
            module = self.parser_registry.parse_file(file_path, source)
            imports = module.imports
            symbol_names = [symbol.name for symbol in symbols_by_file.get(rel_path, []) if symbol.kind != "import"]
            linked_names = [link.symbol_name for link in links_by_file.get(rel_path, [])]
            excerpt = "\n\n".join(imports + module.excerpt_blocks[:12]).strip() or module.raw_excerpt or source[:4000]
            rationale = f"{module.language} slice with imports and top-level definitions relevant to authorized file scope."
            if linked_names:
                rationale += f" Linked imports: {', '.join(linked_names)}."

            slices.append(
                ContextSlice(
                    file_path=rel_path,
                    rationale=rationale,
                    imports=imports,
                    symbols=symbol_names,
                    excerpt=excerpt[:12000],
                )
            )
        return slices
