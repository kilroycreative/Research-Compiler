"""Language-aware parser backends for middle-end indexing and slicing."""

from __future__ import annotations

import ast
import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Protocol


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
    definitions: list[ParsedDefinition] = field(default_factory=list)
    excerpt_blocks: list[str] = field(default_factory=list)
    raw_excerpt: str = ""


class ParserBackend(Protocol):
    language: str

    def supports(self, path: Path) -> bool: ...

    def parse(self, path: Path, source: str) -> ParsedModule: ...


class PythonAstBackend:
    language = "python"

    def supports(self, path: Path) -> bool:
        return path.suffix == ".py"

    def parse(self, path: Path, source: str) -> ParsedModule:
        tree = ast.parse(source, filename=str(path))
        imports: list[str] = []
        definitions: list[ParsedDefinition] = []
        excerpt_blocks: list[str] = []
        for node in tree.body:
            if isinstance(node, (ast.Import, ast.ImportFrom)):
                block = ast.get_source_segment(source, node) or ""
                if block:
                    imports.append(block)
            elif isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
                block = ast.get_source_segment(source, node)
                definitions.append(
                    ParsedDefinition(
                        name=node.name,
                        kind="function",
                        start_line=node.lineno,
                        end_line=getattr(node, "end_lineno", node.lineno),
                        signature=self._function_signature(node),
                        exported=not node.name.startswith("_"),
                        excerpt=block,
                    )
                )
                if block:
                    excerpt_blocks.append(block)
            elif isinstance(node, ast.ClassDef):
                class_block = ast.get_source_segment(source, node)
                definitions.append(
                    ParsedDefinition(
                        name=node.name,
                        kind="class",
                        start_line=node.lineno,
                        end_line=getattr(node, "end_lineno", node.lineno),
                        signature=f"class {node.name}",
                        exported=not node.name.startswith("_"),
                        excerpt=class_block,
                    )
                )
                if class_block:
                    excerpt_blocks.append(class_block)
                for child in node.body:
                    if isinstance(child, (ast.FunctionDef, ast.AsyncFunctionDef)):
                        definitions.append(
                            ParsedDefinition(
                                name=f"{node.name}.{child.name}",
                                kind="method",
                                start_line=child.lineno,
                                end_line=getattr(child, "end_lineno", child.lineno),
                                signature=self._function_signature(child),
                                exported=not child.name.startswith("_"),
                                excerpt=ast.get_source_segment(source, child),
                            )
                        )
            elif isinstance(node, (ast.Assign, ast.AnnAssign)):
                targets = node.targets if isinstance(node, ast.Assign) else [node.target]
                block = ast.get_source_segment(source, node)
                for target in targets:
                    if isinstance(target, ast.Name):
                        definitions.append(
                            ParsedDefinition(
                                name=target.id,
                                kind="assignment",
                                start_line=node.lineno,
                                end_line=getattr(node, "end_lineno", node.lineno),
                                signature=target.id,
                                exported=not target.id.startswith("_"),
                                excerpt=block,
                            )
                        )
                if block:
                    excerpt_blocks.append(block)
        return ParsedModule(
            language=self.language,
            imports=imports,
            definitions=definitions,
            excerpt_blocks=excerpt_blocks,
            raw_excerpt=source[:12000],
        )

    def _function_signature(self, node: ast.FunctionDef | ast.AsyncFunctionDef) -> str:
        return f"{node.name}({', '.join(arg.arg for arg in node.args.args)})"


class RegexScriptBackend:
    """Regex fallback for JS/TS, Go, and Rust-style modules."""

    def __init__(self, *, language: str, suffixes: tuple[str, ...]) -> None:
        self.language = language
        self.suffixes = suffixes
        self.import_patterns = [
            re.compile(r"^\s*import\s.+$", re.MULTILINE),
            re.compile(r"^\s*export\s+import\s.+$", re.MULTILINE),
            re.compile(r"^\s*const\s+\w+\s*=\s*require\(.+\).*$", re.MULTILINE),
            re.compile(r"^\s*use\s+.+;$", re.MULTILINE),
        ]
        self.definition_patterns = [
            ("function", re.compile(r"^\s*(?:export\s+)?function\s+([A-Za-z_][\w]*)\s*\((.*?)\)", re.MULTILINE)),
            ("function", re.compile(r"^\s*(?:export\s+)?const\s+([A-Za-z_][\w]*)\s*=\s*\((.*?)\)\s*=>", re.MULTILINE)),
            ("class", re.compile(r"^\s*(?:export\s+)?class\s+([A-Za-z_][\w]*)", re.MULTILINE)),
            ("class", re.compile(r"^\s*(?:export\s+)?interface\s+([A-Za-z_][\w]*)", re.MULTILINE)),
            ("assignment", re.compile(r"^\s*(?:export\s+)?(?:const|let|var|type)\s+([A-Za-z_][\w]*)", re.MULTILINE)),
            ("function", re.compile(r"^\s*func\s+([A-Za-z_][\w]*)\s*\((.*?)\)", re.MULTILINE)),
            ("class", re.compile(r"^\s*type\s+([A-Za-z_][\w]*)\s+struct", re.MULTILINE)),
            ("function", re.compile(r"^\s*(?:pub\s+)?fn\s+([A-Za-z_][\w]*)\s*\((.*?)\)", re.MULTILINE)),
            ("class", re.compile(r"^\s*(?:pub\s+)?(?:struct|enum|trait)\s+([A-Za-z_][\w]*)", re.MULTILINE)),
        ]

    def supports(self, path: Path) -> bool:
        return path.suffix in self.suffixes

    def parse(self, path: Path, source: str) -> ParsedModule:
        imports: list[str] = []
        for pattern in self.import_patterns:
            imports.extend(match.group(0) for match in pattern.finditer(source))

        definitions: list[ParsedDefinition] = []
        excerpt_blocks: list[str] = []
        seen: set[tuple[str, int]] = set()
        for kind, pattern in self.definition_patterns:
            for match in pattern.finditer(source):
                start = match.start()
                line = source.count("\n", 0, start) + 1
                key = (match.group(1), line)
                if key in seen:
                    continue
                seen.add(key)
                excerpt = self._excerpt_for_line(source, line)
                definitions.append(
                    ParsedDefinition(
                        name=match.group(1),
                        kind=kind,
                        start_line=line,
                        end_line=line,
                        signature=match.group(0).strip(),
                        exported=not match.group(1).startswith("_"),
                        excerpt=excerpt,
                    )
                )
                excerpt_blocks.append(excerpt)
        return ParsedModule(
            language=self.language,
            imports=sorted(set(imports)),
            definitions=definitions,
            excerpt_blocks=excerpt_blocks,
            raw_excerpt=source[:12000],
        )

    def _excerpt_for_line(self, source: str, line_number: int) -> str:
        lines = source.splitlines()
        start = max(0, line_number - 1)
        end = min(len(lines), line_number + 4)
        return "\n".join(lines[start:end]).strip()


class TextBackend:
    language = "text"

    def supports(self, path: Path) -> bool:
        del path
        return True

    def parse(self, path: Path, source: str) -> ParsedModule:
        del path
        return ParsedModule(language=self.language, raw_excerpt=source[:12000])


class TreeSitterBackend:
    """Optional backend placeholder for environments with tree-sitter installed."""

    language = "tree-sitter"

    def __init__(self) -> None:
        self._available = False
        try:
            import tree_sitter  # noqa: F401
        except Exception:
            self._available = False
        else:
            self._available = True

    def supports(self, path: Path) -> bool:
        return self._available and path.suffix in {".py", ".ts", ".tsx", ".js", ".jsx", ".go", ".rs"}

    def parse(self, path: Path, source: str) -> ParsedModule:
        del source
        return ParsedModule(language=f"tree-sitter:{path.suffix.lstrip('.')}", raw_excerpt="")


class ParserRegistry:
    """Selects the best available parser backend for a source file."""

    def __init__(self) -> None:
        self.tree_sitter = TreeSitterBackend()
        self.backends: list[ParserBackend] = [
            PythonAstBackend(),
            RegexScriptBackend(language="typescript", suffixes=(".ts", ".tsx", ".js", ".jsx")),
            RegexScriptBackend(language="go", suffixes=(".go",)),
            RegexScriptBackend(language="rust", suffixes=(".rs",)),
            TextBackend(),
        ]

    def parse_file(self, path: str | Path, source: str) -> ParsedModule:
        file_path = Path(path)
        if self.tree_sitter.supports(file_path):
            parsed = self.tree_sitter.parse(file_path, source)
            if parsed.raw_excerpt or parsed.definitions or parsed.imports:
                return parsed
        for backend in self.backends:
            if backend.supports(file_path):
                return backend.parse(file_path, source)
        return TextBackend().parse(file_path, source)
