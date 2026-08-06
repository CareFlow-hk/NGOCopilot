from __future__ import annotations

from unittest.mock import AsyncMock
from uuid import uuid4

import pytest

from ngopilot_gateway.session_deletion import SessionDeletionService


@pytest.mark.asyncio
async def test_session_deletion_checkpoints_and_purges_before_database_delete() -> None:
    user_id = uuid4()
    events: list[str] = []
    database = AsyncMock()
    database.session_object_keys.return_value = [
        f"tenants/{user_id}/uploads/upload-1",
        f"tenants/{user_id}/artifacts/artifact-1",
    ]
    processes = AsyncMock()
    storage = AsyncMock()
    processes.checkpoint.side_effect = lambda *_: events.append("checkpoint")
    storage.purge_superseded_runtime_snapshots.side_effect = (
        lambda *_: events.append("purge_runtime")
    )
    database.session_object_keys.side_effect = lambda *_: (
        events.append("read_object_keys")
        or [
            f"tenants/{user_id}/uploads/upload-1",
            f"tenants/{user_id}/artifacts/artifact-1",
        ]
    )
    storage.delete_session_objects.side_effect = lambda *_: events.append("delete_objects")
    database.delete_chat_session.side_effect = lambda *_: events.append("delete_database")
    service = SessionDeletionService(database, processes, storage)

    await service.delete(user_id, "session-1")

    processes.checkpoint.assert_awaited_once_with(user_id)
    storage.purge_superseded_runtime_snapshots.assert_awaited_once_with(user_id)
    database.session_object_keys.assert_awaited_once_with(user_id, "session-1")
    storage.delete_session_objects.assert_awaited_once_with(
        user_id,
        [
            f"tenants/{user_id}/uploads/upload-1",
            f"tenants/{user_id}/artifacts/artifact-1",
        ],
    )
    database.delete_chat_session.assert_awaited_once_with(user_id, "session-1")
    assert events == [
        "checkpoint",
        "purge_runtime",
        "read_object_keys",
        "delete_objects",
        "delete_database",
    ]
