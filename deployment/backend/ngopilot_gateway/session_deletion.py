"""Durable deletion of one tenant-owned chat session."""

from __future__ import annotations

from uuid import UUID

from .db import Database
from .processes import TenantProcessManager
from .storage import StorageService


class SessionDeletionService:
    def __init__(
        self,
        db: Database,
        processes: TenantProcessManager,
        storage: StorageService,
    ) -> None:
        self.db = db
        self.processes = processes
        self.storage = storage

    async def delete(self, user_id: UUID, agent_session_id: str) -> None:
        # Goose has already deleted its SQLite rows. Stop it before snapshotting so
        # SQLite is closed and the replacement S3 snapshot is internally consistent.
        await self.processes.checkpoint(user_id)
        await self.storage.purge_superseded_runtime_snapshots(user_id)

        object_keys = await self.db.session_object_keys(user_id, agent_session_id)
        await self.storage.delete_session_objects(user_id, object_keys)
        await self.db.delete_chat_session(user_id, agent_session_id)
