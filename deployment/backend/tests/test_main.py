from __future__ import annotations

import importlib
import logging
from types import SimpleNamespace
from unittest.mock import AsyncMock
from uuid import uuid4

import pytest
from fastapi import WebSocketDisconnect


@pytest.mark.asyncio
async def test_startup_continues_when_stale_cache_eviction_fails(
    settings, monkeypatch, caplog
) -> None:
    events: list[str] = []
    monkeypatch.setenv("APP_ENV", "test")
    main = importlib.import_module("ngopilot_gateway.main")

    async def apply_migrations(*args, **kwargs) -> None:
        events.append("migrations_applied")

    class FakeDatabase:
        def __init__(self, app_settings) -> None:
            events.append("database_created")

        async def connect(self) -> None:
            events.append("database_connected")

        async def close(self) -> None:
            events.append("database_closed")

        async def deleting_chat_sessions(self):
            events.append("pending_deletions_checked")
            return []

    class FakeStorage:
        def __init__(self, app_settings, database) -> None:
            events.append("storage_created")

        async def restore_tenant_cache(self, user_id) -> None:
            raise AssertionError("not called during application startup")

        async def persist_and_evict_tenant_cache(self, user_id) -> None:
            raise AssertionError("not called during application startup")

        async def evict_stale_tenant_caches(self, excluded_user_ids) -> None:
            assert excluded_user_ids == set()
            events.append("cache_eviction_attempted")
            raise RuntimeError("invalid object-storage credentials")

        async def close(self) -> None:
            events.append("storage_closed")

    class FakeProcesses:
        def __init__(self, app_settings, *, restore_cache, evict_cache) -> None:
            events.append("processes_created")

        async def stop_all(self) -> None:
            events.append("processes_stopped")

    monkeypatch.setattr(main, "apply_migrations", apply_migrations)
    monkeypatch.setattr(main, "Database", FakeDatabase)
    monkeypatch.setattr(main, "StorageService", FakeStorage)
    monkeypatch.setattr(main, "TenantProcessManager", FakeProcesses)
    caplog.set_level(logging.ERROR, logger=main.__name__)

    app = main.create_app(settings)
    async with app.router.lifespan_context(app):
        events.append("app_serving")

    assert events == [
        "migrations_applied",
        "database_created",
        "database_connected",
        "storage_created",
        "processes_created",
        "pending_deletions_checked",
        "cache_eviction_attempted",
        "app_serving",
        "processes_stopped",
        "storage_closed",
        "database_closed",
    ]
    assert "Failed to evict stale tenant caches during startup; continuing startup" in caplog.text
    assert "invalid object-storage credentials" in caplog.text


@pytest.mark.asyncio
async def test_acp_startup_failure_closes_accepted_socket_with_server_error(
    settings, monkeypatch, caplog
) -> None:
    monkeypatch.setenv("APP_ENV", "test")
    main = importlib.import_module("ngopilot_gateway.main")

    class FakeWebSocket:
        def __init__(self) -> None:
            self.accepted = False
            self.close = AsyncMock()

        async def accept(self) -> None:
            self.accepted = True

    websocket = FakeWebSocket()

    async def fail_after_accept(websocket, *args) -> None:
        await websocket.accept()
        raise RuntimeError("tenant startup failed")

    monkeypatch.setattr(main, "proxy_websocket", fail_after_accept)
    caplog.set_level(logging.ERROR, logger=main.__name__)

    await main.serve_acp_connection(
        websocket,
        uuid4(),
        settings,
        object(),
        object(),
        object(),
    )

    assert websocket.accepted is True
    websocket.close.assert_awaited_once_with(code=1011)
    assert "ACP connection failed: RuntimeError" in caplog.text


@pytest.mark.asyncio
async def test_acp_client_disconnect_does_not_bubble_or_log_as_failure(
    settings, monkeypatch, caplog
) -> None:
    monkeypatch.setenv("APP_ENV", "test")
    main = importlib.import_module("ngopilot_gateway.main")
    websocket = SimpleNamespace(close=AsyncMock())

    async def disconnect(*args) -> None:
        raise WebSocketDisconnect(code=1000)

    monkeypatch.setattr(main, "proxy_websocket", disconnect)
    caplog.set_level(logging.ERROR, logger=main.__name__)

    await main.serve_acp_connection(
        websocket,
        uuid4(),
        settings,
        object(),
        object(),
        object(),
    )

    websocket.close.assert_not_awaited()
    assert "ACP connection failed" not in caplog.text
