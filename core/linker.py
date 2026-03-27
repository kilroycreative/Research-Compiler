"""Link imported symbols to known definitions."""

from __future__ import annotations

import ast
from pathlib import Path

from .ir import LinkedSymbol, SymbolDefinition


class Linker:
    """Builds a linker map from imports to indexed symbols."""

    def build(self, repo_root: str | Path, file_paths: list[str], symbol_table: list[SymbolDefinition]) -> list[LinkedSymbol]:
        repo = Path(repo_root).resolve()
        by_name: dict[str, list[SymbolDefinition]] = {}
        for symbol in symbol_table:
            by_name.setdefault(symbol.name.split(".")[-1], []).append(symbol)

        linked: list[LinkedSymbol] = []
        for rel_path in sorted(set(file_paths)):
            file_path = repo / rel_path
            if not file_path.exists() or file_path.suffix != ".py":
                continue
            tree = ast.parse(file_path.read_text(encoding="utf-8"), filename=str(file_path))
            for node in tree.body:
                if isinstance(node, ast.ImportFrom):
                    module = node.module
                    for alias in node.names:
                        name = alias.asname or alias.name
                        resolved = self._resolve(module, alias.name, by_name)
                        linked.append(
                            LinkedSymbol(
                                symbol_name=name,
                                file_path=rel_path,
                                source_module=module,
                                resolved_file_path=resolved.file_path if resolved else None,
                                resolved_symbol_name=resolved.name if resolved else None,
                            )
                        )
                elif isinstance(node, ast.Import):
                    for alias in node.names:
                        name = alias.asname or alias.name
                        resolved = self._resolve(alias.name, alias.name.split(".")[-1], by_name)
                        linked.append(
                            LinkedSymbol(
                                symbol_name=name,
                                file_path=rel_path,
                                source_module=alias.name,
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
        dotted_module = module_name.replace(".", "/")
        for candidate in candidates:
            if candidate.file_path.removesuffix(".py").endswith(dotted_module):
                return candidate
        return candidates[0]
