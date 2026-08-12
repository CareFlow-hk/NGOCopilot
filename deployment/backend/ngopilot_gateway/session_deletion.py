"""Durable deletion of one tenant-owned chat session."""

from __future__ import annotations

import asyncio
import logging
from collections.abc import Sequence
from uuid import UUID

from .db import Database
from .processes import TenantProcessManager
from .runtime_sessions import RuntimeSessionStore
from .storage import StorageService

logger = logging.getLogger(__name__)

SESSION_DELETION_RETRY_DELAYS = (1.0, 5.0, 30.0, 120.0, 300.0)


class SessionDeletionService:
    def __init__(
        self,
        db: Database,
        processes: TenantProcessManager,
        storage: StorageService,
        runtime_sessions: RuntimeSessionStore,
        *,
        retry_delays: Sequence[float] = SESSION_DELETION_RETRY_DELAYS,
    ) -> None:
        self.db = db
        self.processes = processes
        self.storage = storage
        self.runtime_sessions = runtime_sessions
        self.retry_delays = tuple(retry_delays)
        self._locks: dict[UUID, asyncio.Lock] = {}
        self._retry_tasks: dict[tuple[UUID, str], asyncio.Task[None]] = {}

    async def delete(self, user_id: UUID, agent_session_id: str) -> bool:
        key = (user_id, agent_session_id[:256])
        async with self._lock(user_id):
            claimed = await self.db.mark_chat_session_deleting(user_id, agent_session_id)
            if not claimed:
                return False
            self._schedule_retry(key, immediate=True)
            return True

    async def resume_pending(self) -> set[UUID]:
        pending = await self.db.deleting_chat_sessions()
        for user_id, agent_session_id in pending:
            self._schedule_retry((user_id, agent_session_id), immediate=True)
        return {user_id for user_id, _ in pending}

    async def close(self) -> None:
        tasks = list(self._retry_tasks.values())
        self._retry_tasks.clear()
        for task in tasks:
            task.cancel()
        if tasks:
            await asyncio.gather(*tasks, return_exceptions=True)

    def _lock(self, user_id: UUID) -> asyncio.Lock:
        lock = self._locks.get(user_id)
        if lock is None:
            lock = asyncio.Lock()
            self._locks[user_id] = lock
        return lock

    async def _delete_marked(self, user_id: UUID, agent_session_id: str) -> bool:
        # Stop Goose before enforcing the SQLite tombstone and snapshotting so the
        # replacement GCS runtime is consistent even after a restart restored old state.
        objects = []

        async def remove_local_session_objects() -> None:
            nonlocal objects
            await self.storage.restore_tenant_cache(user_id)
            await self.runtime_sessions.delete(user_id, agent_session_id)
            objects = await self.db.session_storage_objects(user_id, agent_session_id)
            await self.storage.delete_session_local_objects(user_id, objects)

        await self.processes.checkpoint(
            user_id,
            before_evict=remove_local_session_objects,
        )
        await self.storage.purge_superseded_runtime_snapshots(user_id)
        await self.storage.delete_session_object_versions(user_id, objects)
        return await self.db.delete_chat_session(user_id, agent_session_id)

    def _schedule_retry(self, key: tuple[UUID, str], *, immediate: bool = False) -> None:
        if key in self._retry_tasks or (not immediate and not self.retry_delays):
            return
        delays = ((0.0,) if immediate else ()) + self.retry_delays
        task = asyncio.create_task(
            self._retry(key, delays),
            name=f"session-deletion-{key[0]}-{key[1]}",
        )
        self._retry_tasks[key] = task
        task.add_done_callback(
            lambda completed, retry_key=key: self._retry_done(retry_key, completed)
        )

    def _retry_done(self, key: tuple[UUID, str], task: asyncio.Task[None]) -> None:
        if self._retry_tasks.get(key) is task:
            self._retry_tasks.pop(key, None)
        if not task.cancelled() and task.exception() is not None:
            logger.error(
                "Session deletion retry task failed for user %s: %s",
                key[0],
                type(task.exception()).__name__,
            )

    async def _retry(self, key: tuple[UUID, str], delays: Sequence[float]) -> None:
        user_id, agent_session_id = key
        for delay in delays:
            if delay > 0:
                await asyncio.sleep(delay)
            try:
                async with self._lock(user_id):
                    if not await self.db.chat_session_is_deleting(user_id, agent_session_id):
                        return
                    await self._delete_marked(user_id, agent_session_id)
                return
            except asyncio.CancelledError:
                raise
            except Exception:
                logger.exception("Retrying incomplete session deletion for user %s", user_id)
        logger.error("Session deletion remains incomplete for user %s", user_id)
