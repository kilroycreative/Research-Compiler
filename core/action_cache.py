"""SQLite-backed cache for verified compiler actions."""

from __future__ import annotations

import json
import sqlite3
from dataclasses import dataclass
from datetime import UTC, datetime
from hashlib import sha256
from pathlib import Path
from typing import Any

from .ir import FrontendIR


def _canonical_json(value: Any) -> str:
    return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=True)


@dataclass(frozen=True)
class CachedAction:
    action_key: str
    patch: str
    verification_summary: dict[str, Any]
    frontend_ir: dict[str, Any]
    constitution: str
    created_at: str


class ActionCache:
    """Stores verified patches keyed by deterministic IR-derived hashes."""

    SCHEMA_VERSION = 1

    def __init__(self, db_path: str | Path) -> None:
        self.db_path = Path(db_path)
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        self._initialize()

    @classmethod
    def compute_action_key(
        cls,
        frontend_ir: FrontendIR,
        constitution: str,
        *,
        namespace: str = "action-cache-v1",
    ) -> str:
        payload = {
            "namespace": namespace,
            "schema_version": cls.SCHEMA_VERSION,
            "frontend_ir": frontend_ir.model_dump(mode="json"),
            "base_commit": frontend_ir.base_commit,
            "constitution": constitution,
        }
        return sha256(_canonical_json(payload).encode("utf-8")).hexdigest()

    def get(self, action_key: str) -> CachedAction | None:
        with self._connect() as connection:
            row = connection.execute(
                """
                SELECT action_key, patch, verification_summary_json, frontend_ir_json, constitution, created_at
                FROM action_cache
                WHERE action_key = ?
                """,
                (action_key,),
            ).fetchone()
        if row is None:
            return None
        return CachedAction(
            action_key=row["action_key"],
            patch=row["patch"],
            verification_summary=json.loads(row["verification_summary_json"]),
            frontend_ir=json.loads(row["frontend_ir_json"]),
            constitution=row["constitution"],
            created_at=row["created_at"],
        )

    def get_by_inputs(self, frontend_ir: FrontendIR, constitution: str) -> CachedAction | None:
        return self.get(self.compute_action_key(frontend_ir, constitution))

    def put(
        self,
        frontend_ir: FrontendIR,
        constitution: str,
        *,
        patch: str,
        verification_summary: dict[str, Any],
    ) -> str:
        action_key = self.compute_action_key(frontend_ir, constitution)
        created_at = datetime.now(UTC).isoformat()
        with self._connect() as connection:
            connection.execute(
                """
                INSERT INTO action_cache (
                    action_key,
                    patch,
                    verification_summary_json,
                    frontend_ir_json,
                    constitution,
                    created_at
                )
                VALUES (?, ?, ?, ?, ?, ?)
                ON CONFLICT(action_key) DO UPDATE SET
                    patch = excluded.patch,
                    verification_summary_json = excluded.verification_summary_json,
                    frontend_ir_json = excluded.frontend_ir_json,
                    constitution = excluded.constitution,
                    created_at = excluded.created_at
                """,
                (
                    action_key,
                    patch,
                    _canonical_json(verification_summary),
                    _canonical_json(frontend_ir.model_dump(mode="json")),
                    constitution,
                    created_at,
                ),
            )
        return action_key

    def _initialize(self) -> None:
        with self._connect() as connection:
            connection.executescript(
                """
                PRAGMA journal_mode = WAL;

                CREATE TABLE IF NOT EXISTS action_cache (
                    action_key TEXT PRIMARY KEY,
                    patch TEXT NOT NULL,
                    verification_summary_json TEXT NOT NULL,
                    frontend_ir_json TEXT NOT NULL,
                    constitution TEXT NOT NULL,
                    created_at TEXT NOT NULL
                );
                """
            )

    def _connect(self) -> sqlite3.Connection:
        connection = sqlite3.connect(self.db_path)
        connection.row_factory = sqlite3.Row
        return connection
