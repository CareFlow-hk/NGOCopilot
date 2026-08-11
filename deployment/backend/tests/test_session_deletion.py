from __future__ import annotations

import asyncio
from unittest.mock import AsyncMock
from uuid import uuid4

import pytest

from ngopilot_gateway.session_deletion import SessionDeletionService


@pytest.mark.asyncio
async def test_session_deletion_marks_and_purges_before_database_delete() -> None:
    user_id = uuid4()
    events: list[str] = []
    database = AsyncMock()
    objects = [
        {
            "id": uuid4(),
            "object_key": f"tenants/{user_id}/uploads/upload-1",
            "local_path": f"tenants/{user_id}/uploads/upload-1/source.xlsx",
        },
        {
            "id": uuid4(),
            "object_key": f"tenants/{user_id}/artifacts/artifact-1",
            "local_path": f"tenants/{user_id}/workflow/output.xlsx",
        },
    ]
    processes = AsyncMock()
    storage = AsyncMock()
    runtime_sessions = AsyncMock()
    database.mark_chat_session_deleting.side_effect = lambda *_: (
        events.append("mark_deleting") or True
    )

    async def checkpoint(*_, before_evict):
        events.append("stop_process")
        await before_evict()
        events.append("commit_snapshot")

    processes.checkpoint.side_effect = checkpoint
    storage.restore_tenant_cache.side_effect = lambda *_: events.append("restore_cache")
    runtime_sessions.delete.side_effect = lambda *_: events.append("delete_runtime_session")
    storage.purge_superseded_runtime_snapshots.side_effect = lambda *_: events.append(
        "purge_runtime"
    )
    database.session_storage_objects.side_effect = lambda *_: (
        events.append("read_objects") or objects
    )
    storage.delete_session_local_objects.side_effect = lambda *_: events.append(
        "delete_local_objects"
    )
    storage.delete_session_object_versions.side_effect = lambda *_: events.append(
        "delete_gcs_objects"
    )
    database.delete_chat_session.side_effect = lambda *_: events.append("delete_database") or True
    service = SessionDeletionService(
        database, processes, storage, runtime_sessions, retry_delays=()
    )

    assert await service.delete(user_id, "session-1") is True

    database.mark_chat_session_deleting.assert_awaited_once_with(user_id, "session-1")
    assert processes.checkpoint.await_count == 1
    assert processes.checkpoint.await_args.args == (user_id,)
    assert callable(processes.checkpoint.await_args.kwargs["before_evict"])
    storage.restore_tenant_cache.assert_awaited_once_with(user_id)
    runtime_sessions.delete.assert_awaited_once_with(user_id, "session-1")
    storage.purge_superseded_runtime_snapshots.assert_awaited_once_with(user_id)
    database.session_storage_objects.assert_awaited_once_with(user_id, "session-1")
    storage.delete_session_local_objects.assert_awaited_once_with(user_id, objects)
    storage.delete_session_object_versions.assert_awaited_once_with(user_id, objects)
    database.delete_chat_session.assert_awaited_once_with(user_id, "session-1")
    assert events == [
        "mark_deleting",
        "stop_process",
        "restore_cache",
        "delete_runtime_session",
        "read_objects",
        "delete_local_objects",
        "commit_snapshot",
        "purge_runtime",
        "delete_gcs_objects",
        "delete_database",
    ]


@pytest.mark.asyncio
async def test_session_deletion_does_not_touch_unowned_session() -> None:
    database = AsyncMock()
    database.mark_chat_session_deleting.return_value = False
    processes = AsyncMock()
    storage = AsyncMock()
    runtime_sessions = AsyncMock()
    service = SessionDeletionService(
        database, processes, storage, runtime_sessions, retry_delays=()
    )

    assert await service.delete(uuid4(), "another-users-session") is False

    processes.checkpoint.assert_not_awaited()
    storage.restore_tenant_cache.assert_not_awaited()
    runtime_sessions.delete.assert_not_awaited()
    storage.delete_session_local_objects.assert_not_awaited()
    storage.delete_session_object_versions.assert_not_awaited()
    database.delete_chat_session.assert_not_awaited()


@pytest.mark.asyncio
async def test_failed_cleanup_is_retried_from_durable_deleting_state() -> None:
    user_id = uuid4()
    database = AsyncMock()
    database.mark_chat_session_deleting.return_value = True
    database.chat_session_is_deleting.return_value = True
    database.session_storage_objects.return_value = []
    database.delete_chat_session.return_value = True
    processes = AsyncMock()
    storage = AsyncMock()
    runtime_sessions = AsyncMock()

    async def checkpoint(*_, before_evict):
        await before_evict()

    processes.checkpoint.side_effect = checkpoint
    storage.purge_superseded_runtime_snapshots.side_effect = [
        RuntimeError("temporary GCS failure"),
        None,
    ]
    service = SessionDeletionService(
        database, processes, storage, runtime_sessions, retry_delays=(0,)
    )

    with pytest.raises(RuntimeError, match="temporary GCS failure"):
        await service.delete(user_id, "session-1")

    retry_task = service._retry_tasks[(user_id, "session-1")]
    await retry_task

    assert storage.purge_superseded_runtime_snapshots.await_count == 2
    database.delete_chat_session.assert_awaited_once_with(user_id, "session-1")


@pytest.mark.asyncio
async def test_same_tenant_session_deletions_are_serialized() -> None:
    user_id = uuid4()
    database = AsyncMock()
    database.mark_chat_session_deleting.return_value = True
    database.session_storage_objects.return_value = []
    database.delete_chat_session.return_value = True
    processes = AsyncMock()
    storage = AsyncMock()
    runtime_sessions = AsyncMock()
    active = 0
    max_active = 0

    async def checkpoint(*_, before_evict):
        nonlocal active, max_active
        active += 1
        max_active = max(max_active, active)
        await before_evict()
        await asyncio.sleep(0)
        active -= 1

    processes.checkpoint.side_effect = checkpoint
    service = SessionDeletionService(
        database, processes, storage, runtime_sessions, retry_delays=()
    )

    assert await asyncio.gather(
        service.delete(user_id, "session-1"),
        service.delete(user_id, "session-2"),
    ) == [True, True]

    assert max_active == 1
    assert storage.restore_tenant_cache.await_count == 2
