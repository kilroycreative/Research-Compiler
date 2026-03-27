"""Query-driven tree-sitter adapter for polyglot slicing and symbol extraction."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from ..parser_types import ParsedDefinition, ParsedImport, ParsedModule

try:
    from tree_sitter import Query, QueryCursor
    from tree_sitter_language_pack import get_language, get_parser
except Exception:  # pragma: no cover - optional dependency fallback
    Query = None
    QueryCursor = None
    get_language = None
    get_parser = None


@dataclass(frozen=True)
class LanguagePack:
    language: str
    suffixes: tuple[str, ...]
    query_language: str


class TreeSitterAdapter:
    """Loads tree-sitter grammars and .scm query files for supported languages."""

    def __init__(self) -> None:
        self.query_root = Path(__file__).resolve().parent / "queries"
        self.language_packs = [
            LanguagePack(language="python", suffixes=(".py",), query_language="python"),
            LanguagePack(language="typescript", suffixes=(".ts",), query_language="typescript"),
            LanguagePack(language="tsx", suffixes=(".tsx",), query_language="typescript"),
            LanguagePack(language="javascript", suffixes=(".js", ".jsx"), query_language="typescript"),
            LanguagePack(language="go", suffixes=(".go",), query_language="go"),
            LanguagePack(language="rust", suffixes=(".rs",), query_language="rust"),
        ]
        self._query_cache: dict[tuple[str, str], Query] = {}

    def supports(self, path: Path) -> bool:
        if Query is None or get_language is None or get_parser is None:
            return False
        return self._pack_for_path(path) is not None

    def parse(self, path: Path, source: str) -> ParsedModule:
        pack = self._pack_for_path(path)
        if pack is None or Query is None or QueryCursor is None or get_language is None or get_parser is None:
            return ParsedModule(language="tree-sitter-unavailable", raw_excerpt=source[:12000])

        parser = get_parser(pack.language)
        tree = parser.parse(source.encode("utf-8"))
        root = tree.root_node
        definition_query = self._load_query(pack, "definitions")
        import_query = self._load_query(pack, "imports")

        definitions = self._extract_definitions(root, source, definition_query)
        import_entries = self._extract_imports(root, source, import_query)
        imports = sorted({entry.statement or self._render_import(entry) for entry in import_entries})
        excerpt_blocks = [definition.excerpt for definition in definitions if definition.excerpt][:12]
        raw_excerpt = source[:12000]
        return ParsedModule(
            language=f"tree-sitter:{pack.language}",
            imports=imports,
            import_entries=import_entries,
            definitions=definitions,
            excerpt_blocks=excerpt_blocks,
            raw_excerpt=raw_excerpt,
            has_errors=root.has_error,
        )

    def _pack_for_path(self, path: Path) -> LanguagePack | None:
        suffix = path.suffix.lower()
        for pack in self.language_packs:
            if suffix in pack.suffixes:
                return pack
        return None

    def _load_query(self, pack: LanguagePack, name: str) -> Query:
        key = (pack.query_language, name)
        if key in self._query_cache:
            return self._query_cache[key]
        query_path = self.query_root / pack.query_language / f"{name}.scm"
        query_text = query_path.read_text(encoding="utf-8")
        query = Query(get_language(pack.language), query_text)
        self._query_cache[key] = query
        return query

    def _extract_definitions(self, root, source: str, query: Query) -> list[ParsedDefinition]:
        cursor = QueryCursor(query)
        results: list[ParsedDefinition] = []
        for _pattern_index, captures in cursor.matches(root):
            keys = set(captures)
            if "class.name" in keys and "method.name" in keys:
                class_name = self._node_text(source, captures["class.name"][0])
                for definition_node, name_node in zip(captures.get("method.definition", []), captures.get("method.name", []), strict=False):
                    method_name = self._node_text(source, name_node)
                    results.append(
                        self._definition_from_nodes(
                            source=source,
                            definition_node=definition_node,
                            name=f"{class_name}.{method_name}",
                            kind="method",
                        )
                    )
                continue
            for prefix, kind in [
                ("function", "function"),
                ("class", "class"),
                ("assignment", "assignment"),
            ]:
                name_key = f"{prefix}.name"
                definition_key = f"{prefix}.definition"
                if name_key in keys and definition_key in keys:
                    results.append(
                        self._definition_from_nodes(
                            source=source,
                            definition_node=captures[definition_key][0],
                            name=self._node_text(source, captures[name_key][0]),
                            kind=kind,
                        )
                    )
                    break
        deduped: dict[tuple[str, str, int], ParsedDefinition] = {}
        for item in results:
            deduped[(item.kind, item.name, item.start_line)] = item
        return list(deduped.values())

    def _extract_imports(self, root, source: str, query: Query) -> list[ParsedImport]:
        cursor = QueryCursor(query)
        entries: list[ParsedImport] = []
        for _pattern_index, captures in cursor.matches(root):
            module = self._capture_text(source, captures, "import.module")
            if module is None:
                continue
            imported_name = self._capture_text(source, captures, "import.name")
            alias = self._capture_text(source, captures, "import.alias")
            statement_node = captures.get("import.statement", [None])[0]
            statement = self._node_text(source, statement_node) if statement_node is not None else None
            entries.append(
                ParsedImport(
                    module=self._strip_quotes(module),
                    imported_name=imported_name,
                    alias=alias or imported_name or module.split("::")[-1].split(".")[-1].split("/")[-1],
                    statement=statement,
                )
            )
        deduped: dict[tuple[str, str | None, str | None], ParsedImport] = {}
        for entry in entries:
            deduped[(entry.module, entry.imported_name, entry.alias)] = entry
        return list(deduped.values())

    def _definition_from_nodes(self, *, source: str, definition_node, name: str, kind: str) -> ParsedDefinition:
        excerpt = self._node_text(source, definition_node)
        return ParsedDefinition(
            name=name,
            kind=kind,
            start_line=definition_node.start_point.row + 1,
            end_line=definition_node.end_point.row + 1,
            signature=excerpt.splitlines()[0].strip() if excerpt else name,
            exported=not name.split(".")[-1].startswith("_"),
            excerpt=excerpt,
        )

    def _capture_text(self, source: str, captures: dict[str, list], key: str) -> str | None:
        nodes = captures.get(key)
        if not nodes:
            return None
        return self._node_text(source, nodes[0])

    def _node_text(self, source: str, node) -> str:
        return source[node.start_byte : node.end_byte]

    def _render_import(self, entry: ParsedImport) -> str:
        if entry.imported_name:
            alias = f" as {entry.alias}" if entry.alias and entry.alias != entry.imported_name else ""
            return f"from {entry.module} import {entry.imported_name}{alias}"
        return f"import {entry.module}"

    def _strip_quotes(self, value: str) -> str:
        if len(value) >= 2 and value[0] == value[-1] and value[0] in {'"', "'"}:
            return value[1:-1]
        return value
