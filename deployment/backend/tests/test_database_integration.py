from __future__ import annotations

import hashlib
import os
from pathlib import Path
from uuid import uuid4

import pytest

from ngopilot_gateway.config import Settings
from ngopilot_gateway.db import Database, apply_migrations

DATABASE_URL = os.getenv("TEST_DATABASE_URL")


@pytest.mark.skipif(not DATABASE_URL, reason="TEST_DATABASE_URL is not set")
@pytest.mark.asyncio
async def test_migration_auth_ticket_and_chat_projection() -> None:
    assert DATABASE_URL is not None
    migrations = Path(__file__).resolve().parents[1] / "ngopilot_gateway" / "migrations"
    assert await apply_migrations(DATABASE_URL, migrations) == [1, 2]
    assert await apply_migrations(DATABASE_URL, migrations) == []

    settings = Settings(
        app_env="test",
        database_url=DATABASE_URL,
        public_api_url="http://127.0.0.1:8080",
        allowed_origins="http://127.0.0.1:4173",
    )
    database = Database(settings)
    await database.connect()
    try:
        email = f"integration-{uuid4()}@example.test"
        user = await database.create_user(email, "x" * 32, "Integration User")
        auth_token = hashlib.sha256(b"auth-token").digest()
        auth_session = await database.create_auth_session(user["id"], auth_token, 1)
        context = await database.auth_context(auth_token)
        assert context is not None
        assert context["user_id"] == user["id"]

        ticket = hashlib.sha256(b"ws-ticket").digest()
        await database.create_ws_ticket(user["id"], auth_session["id"], ticket, 60)
        assert await database.consume_ws_ticket(ticket) is not None
        assert await database.consume_ws_ticket(ticket) is None

        first_session = await database.upsert_chat_session(
            user["id"], "agent-session-1", "moonshotai/kimi-k2.6"
        )
        second_session = await database.upsert_chat_session(
            user["id"], "agent-session-2", "moonshotai/kimi-k2.6"
        )
        await database.record_message(
            user["id"], "agent-session-1", "user", "prompt", [{"text": "Hello"}]
        )
        count = await database._pool().fetchval(
            "SELECT count(*) FROM messages WHERE user_id = $1", user["id"]
        )
        assert count == 1

        object_id = uuid4()
        await database._pool().execute(
            """
            INSERT INTO storage_objects (
                id, user_id, kind, filename, content_type, size_bytes, sha256,
                local_path, object_key, status, verified_at
            ) VALUES (
                $1, $2, 'artifact', 'shared.xlsx', 'application/octet-stream',
                1, $3, $4, $5, 'ready', now()
            )
            """,
            object_id,
            user["id"],
            "a" * 64,
            f"tenants/{user['id']}/workflow/shared.xlsx",
            f"tenants/{user['id']}/artifacts/{object_id}",
        )
        await database._pool().executemany(
            """
            INSERT INTO session_storage_objects (user_id, session_id, storage_object_id)
            VALUES ($1, $2, $3)
            """,
            [
                (user["id"], first_session["id"], object_id),
                (user["id"], second_session["id"], object_id),
            ],
        )

        assert await database.session_storage_objects(user["id"], "agent-session-1") == []

        assert await database.delete_chat_session(user["id"], "agent-session-1") is True
        remaining = await database._pool().fetchval(
            "SELECT count(*) FROM chat_sessions WHERE user_id = $1", user["id"]
        )
        messages = await database._pool().fetchval(
            "SELECT count(*) FROM messages WHERE user_id = $1", user["id"]
        )
        shared_objects = await database._pool().fetchval(
            "SELECT count(*) FROM storage_objects WHERE id = $1", object_id
        )
        assert remaining == 1
        assert messages == 0
        assert shared_objects == 1

        assert len(await database.session_storage_objects(user["id"], "agent-session-2")) == 1
        await database.upsert_job(
            user["id"],
            "agent-session-2",
            "job-session-2",
            "careflow",
            {"status": "completed"},
        )
        job_artifact_id = uuid4()
        await database.upsert_artifact(
            artifact_id=job_artifact_id,
            user_id=user["id"],
            job_id="job-session-2",
            agent_session_id=None,
            filename="job-only.xlsx",
            content_type="application/octet-stream",
            size_bytes=1,
            sha256="b" * 64,
            local_path=f"tenants/{user['id']}/workflow/job-only.xlsx",
            object_key=f"tenants/{user['id']}/artifacts/{job_artifact_id}",
        )
        assert len(await database.session_storage_objects(user["id"], "agent-session-2")) == 2
        assert await database.delete_chat_session(user["id"], "agent-session-2") is True
        assert (
            await database._pool().fetchval(
                "SELECT count(*) FROM storage_objects WHERE id = $1", object_id
            )
            == 0
        )
        assert (
            await database._pool().fetchval(
                "SELECT count(*) FROM storage_objects WHERE id = $1", job_artifact_id
            )
            == 0
        )
    finally:
        await database.close()
