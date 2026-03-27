"""Persistent cache for compiler analysis artifacts."""

from __future__ import annotations

import hashlib
import json
import sqlite3
from pathlib import Path
from typing import Any

from .ir import ContextSlice, LinkedSymbol, SymbolDefinition


def _canonical_json(value: Any) -> str:
    return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=True)


class OptimizerCache:
    """Caches symbol tables, linker maps, and context slices by content digest."""

    ANALYZER_VERSION = "optimizer-v1"

    def __init__(self, db_path: str | Path) -> None:
        self.db_path = Path(db_path)
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        self._initialize()

    def compute_key(self, repo_root: str | Path, file_paths: list[str], task_context: str) -> str:
        repo = Path(repo_root).resolve()
        file_state = []
        for rel_path in sorted(set(file_paths)):
            file_path = repo / rel_path
            if file_path.exists():
                content = file_path.read_text(encoding="utf-8")
                digest = hashlib.sha256(content.encode("utf-8")).hexdigest()
            else:
                digest = "missing"
            file_state.append({"path": rel_path, "digest": digest})
        payload = {
            "analyzer_version": self.ANALYZER_VERSION,
            "files": file_state,
            "task_context": task_context,
        }
        return hashlib.sha256(_canonical_json(payload).encode("utf-8")).hexdigest()

    def get(self, key: str) -> dict[str, list[Any]] | None:
        with self._connect() as connection:
            row = connection.execute(
                "SELECT symbol_table_json, linker_map_json, context_slices_json FROM optimizer_cache WHERE cache_key = ?",
                (key,),
            ).fetchone()
        if row is None:
            return None
        return {
            "symbol_table": [SymbolDefinition.model_validate(item) for item in json.loads(row["symbol_table_json"])],
            "linker_map": [LinkedSymbol.model_validate(item) for item in json.loads(row["linker_map_json"])],
            "context_slices": [ContextSlice.model_validate(item) for item in json.loads(row["context_slices_json"])],
        }

    def put(
        self,
        key: str,
        *,
        symbol_table: list[SymbolDefinition],
        linker_map: list[LinkedSymbol],
        context_slices: list[ContextSlice],
    ) -> None:
        with self._connect() as connection:
            connection.execute(
                """
                INSERT INTO optimizer_cache (cache_key, symbol_table_json, linker_map_json, context_slices_json)
                VALUES (?, ?, ?, ?)
                ON CONFLICT(cache_key) DO UPDATE SET
                    symbol_table_json = excluded.symbol_table_json,
                    linker_map_json = excluded.linker_map_json,
                    context_slices_json = excluded.context_slices_json
                """,
                (
                    key,
                    _canonical_json([item.model_dump(mode="json") for item in symbol_table]),
                    _canonical_json([item.model_dump(mode="json") for item in linker_map]),
                    _canonical_json([item.model_dump(mode="json") for item in context_slices]),
                ),
            )

    def _initialize(self) -> None:
        with self._connect() as connection:
            connection.executescript(
                """
                CREATE TABLE IF NOT EXISTS optimizer_cache (
                    cache_key TEXT PRIMARY KEY,
                    symbol_table_json TEXT NOT NULL,
                    linker_map_json TEXT NOT NULL,
                    context_slices_json TEXT NOT NULL
                );
                """
            )

    def _connect(self) -> sqlite3.Connection:
        connection = sqlite3.connect(self.db_path)
        connection.row_factory = sqlite3.Row
        return connection
