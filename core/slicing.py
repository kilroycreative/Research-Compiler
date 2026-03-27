"""AST-aware context slicing for model prompts."""

from __future__ import annotations

import ast
from pathlib import Path

from .ir import ContextSlice, LinkedSymbol, SymbolDefinition


class ContextPruner:
    """Builds minimal file slices around imports and top-level symbols."""

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
            if file_path.suffix != ".py":
                content = file_path.read_text(encoding="utf-8")
                slices.append(
                    ContextSlice(
                        file_path=rel_path,
                        rationale="Non-Python file; include raw content.",
                        imports=[],
                        symbols=[],
                        excerpt=content[:4000],
                    )
                )
                continue

            source = file_path.read_text(encoding="utf-8")
            tree = ast.parse(source, filename=str(file_path))
            imports = [line for line in source.splitlines() if line.startswith("import ") or line.startswith("from ")]
            symbol_names = [symbol.name for symbol in symbols_by_file.get(rel_path, []) if symbol.kind != "import"]
            linked_names = [link.symbol_name for link in links_by_file.get(rel_path, [])]

            excerpt_blocks: list[str] = []
            for node in tree.body:
                if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
                    block = ast.get_source_segment(source, node)
                    if block:
                        excerpt_blocks.append(block)
                elif isinstance(node, (ast.Assign, ast.AnnAssign)):
                    block = ast.get_source_segment(source, node)
                    if block:
                        excerpt_blocks.append(block)
            excerpt = "\n\n".join(imports + excerpt_blocks[:12]).strip() or source[:4000]
            rationale = "Python AST slice with imports and top-level definitions relevant to authorized file scope."
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
