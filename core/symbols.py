"""Symbol indexing for the compiler middle-end."""

from __future__ import annotations

import ast
from pathlib import Path

from .ir import SymbolDefinition


class SymbolTableBuilder:
    """Builds a simple persistent-friendly symbol view for Python source files."""

    def build(self, repo_root: str | Path, file_paths: list[str]) -> list[SymbolDefinition]:
        repo = Path(repo_root).resolve()
        symbols: list[SymbolDefinition] = []
        for rel_path in sorted(set(file_paths)):
            file_path = repo / rel_path
            if not file_path.exists() or file_path.suffix != ".py":
                continue
            source = file_path.read_text(encoding="utf-8")
            tree = ast.parse(source, filename=str(file_path))
            symbols.extend(self._collect_module_symbols(rel_path, tree))
        return symbols

    def _collect_module_symbols(self, rel_path: str, tree: ast.Module) -> list[SymbolDefinition]:
        collected: list[SymbolDefinition] = []
        for node in tree.body:
            if isinstance(node, (ast.Import, ast.ImportFrom)):
                for alias in node.names:
                    collected.append(
                        SymbolDefinition(
                            name=alias.asname or alias.name,
                            kind="import",
                            file_path=rel_path,
                            start_line=node.lineno,
                            end_line=getattr(node, "end_lineno", node.lineno),
                            signature=alias.name,
                            exported=not (alias.asname or alias.name).startswith("_"),
                        )
                    )
            elif isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
                collected.append(
                    SymbolDefinition(
                        name=node.name,
                        kind="function",
                        file_path=rel_path,
                        start_line=node.lineno,
                        end_line=getattr(node, "end_lineno", node.lineno),
                        signature=self._function_signature(node),
                        exported=not node.name.startswith("_"),
                    )
                )
            elif isinstance(node, ast.ClassDef):
                collected.append(
                    SymbolDefinition(
                        name=node.name,
                        kind="class",
                        file_path=rel_path,
                        start_line=node.lineno,
                        end_line=getattr(node, "end_lineno", node.lineno),
                        signature=f"class {node.name}",
                        exported=not node.name.startswith("_"),
                    )
                )
                for child in node.body:
                    if isinstance(child, (ast.FunctionDef, ast.AsyncFunctionDef)):
                        collected.append(
                            SymbolDefinition(
                                name=f"{node.name}.{child.name}",
                                kind="method",
                                file_path=rel_path,
                                start_line=child.lineno,
                                end_line=getattr(child, "end_lineno", child.lineno),
                                signature=self._function_signature(child),
                                exported=not child.name.startswith("_"),
                            )
                        )
            elif isinstance(node, (ast.Assign, ast.AnnAssign)):
                targets = node.targets if isinstance(node, ast.Assign) else [node.target]
                for target in targets:
                    if isinstance(target, ast.Name):
                        collected.append(
                            SymbolDefinition(
                                name=target.id,
                                kind="assignment",
                                file_path=rel_path,
                                start_line=node.lineno,
                                end_line=getattr(node, "end_lineno", node.lineno),
                                signature=target.id,
                                exported=not target.id.startswith("_"),
                            )
                        )
        return collected

    def _function_signature(self, node: ast.FunctionDef | ast.AsyncFunctionDef) -> str:
        args = []
        for arg in node.args.args:
            args.append(arg.arg)
        return f"{node.name}({', '.join(args)})"
