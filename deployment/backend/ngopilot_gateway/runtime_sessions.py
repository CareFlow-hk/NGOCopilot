"""Idempotent cleanup for the tenant-local Goose session database."""

from __future__ import annotations

import asyncio
import sqlite3
from pathlib import Path
from uuid import UUID


class RuntimeSessionStore:
    def __init__(self, data_root: Path) -> None:
        self.data_root = data_root

    async def delete(self, user_id: UUID, agent_session_id: str) -> bool:
        return await asyncio.to_thread(self._delete, user_id, agent_session_id[:256])

    def _delete(self, user_id: UUID, agent_session_id: str) -> bool:
        data_root = self.data_root.resolve()
        relative = Path("tenants") / str(user_id) / "goose" / "data" / "sessions" / "sessions.db"
        database_path = data_root / relative
        if not database_path.exists():
            return False

        current = data_root
        for part in relative.parts:
            current = current / part
            if current.is_symlink():
                raise RuntimeError("Tenant session database path contains a symbolic link")
        if not database_path.is_file():
            raise RuntimeError("Tenant session database path is not a file")

        resolved_path = database_path.resolve(strict=True)
        tenant_root = data_root / "tenants" / str(user_id)
        if not resolved_path.is_relative_to(tenant_root):
            raise RuntimeError("Tenant session database is outside the tenant directory")

        connection = sqlite3.connect(resolved_path, timeout=30, isolation_level=None)
        try:
            connection.execute("PRAGMA foreign_keys = ON")
            tables = {
                str(row[0])
                for row in connection.execute("SELECT name FROM sqlite_master WHERE type = 'table'")
            }
            if "sessions" not in tables:
                raise RuntimeError("Tenant session database schema is invalid")

            connection.execute("BEGIN IMMEDIATE")
            if "messages" in tables:
                connection.execute("DELETE FROM messages WHERE session_id = ?", (agent_session_id,))
            if "usage_ledger" in tables:
                connection.execute(
                    "DELETE FROM usage_ledger WHERE session_id = ?", (agent_session_id,)
                )
            deleted = connection.execute(
                "DELETE FROM sessions WHERE id = ?", (agent_session_id,)
            ).rowcount
            connection.commit()
            connection.execute("PRAGMA wal_checkpoint(TRUNCATE)")
            return deleted == 1
        except Exception:
            if connection.in_transaction:
                connection.rollback()
            raise
        finally:
            connection.close()
