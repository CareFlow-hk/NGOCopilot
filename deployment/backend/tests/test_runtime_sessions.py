from __future__ import annotations

import sqlite3
from pathlib import Path
from uuid import uuid4

import pytest

from ngopilot_gateway.runtime_sessions import RuntimeSessionStore


def create_session_database(path: Path) -> None:
    path.parent.mkdir(parents=True)
    with sqlite3.connect(path) as connection:
        connection.executescript(
            """
            CREATE TABLE sessions (id TEXT PRIMARY KEY);
            CREATE TABLE messages (
                id INTEGER PRIMARY KEY,
                session_id TEXT NOT NULL REFERENCES sessions(id) ON DELETE CASCADE
            );
            CREATE TABLE usage_ledger (
                id INTEGER PRIMARY KEY,
                session_id TEXT NOT NULL REFERENCES sessions(id) ON DELETE CASCADE
            );
            INSERT INTO sessions (id) VALUES ('session-1'), ('session-2');
            INSERT INTO messages (session_id) VALUES ('session-1'), ('session-2');
            INSERT INTO usage_ledger (session_id) VALUES ('session-1'), ('session-2');
            """
        )


@pytest.mark.asyncio
async def test_runtime_session_delete_is_scoped_and_idempotent(settings) -> None:
    user_id = uuid4()
    database_path = (
        settings.data_root
        / "tenants"
        / str(user_id)
        / "goose"
        / "data"
        / "sessions"
        / "sessions.db"
    )
    create_session_database(database_path)
    store = RuntimeSessionStore(settings.data_root)

    assert await store.delete(user_id, "session-1") is True
    assert await store.delete(user_id, "session-1") is False

    with sqlite3.connect(database_path) as connection:
        assert connection.execute("SELECT id FROM sessions").fetchall() == [("session-2",)]
        assert connection.execute("SELECT session_id FROM messages").fetchall() == [("session-2",)]
        assert connection.execute("SELECT session_id FROM usage_ledger").fetchall() == [
            ("session-2",)
        ]


@pytest.mark.asyncio
async def test_runtime_session_delete_does_not_create_a_missing_database(settings) -> None:
    store = RuntimeSessionStore(settings.data_root)

    assert await store.delete(uuid4(), "missing-session") is False
    assert not settings.data_root.exists()
