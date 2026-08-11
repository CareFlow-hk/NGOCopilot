from __future__ import annotations

import importlib
import logging

import pytest


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

    class FakeStorage:
        def __init__(self, app_settings, database) -> None:
            events.append("storage_created")

        async def restore_tenant_cache(self, user_id) -> None:
            raise AssertionError("not called during application startup")

        async def persist_and_evict_tenant_cache(self, user_id) -> None:
            raise AssertionError("not called during application startup")

        async def evict_stale_tenant_caches(self) -> None:
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
        "cache_eviction_attempted",
        "app_serving",
        "processes_stopped",
        "storage_closed",
        "database_closed",
    ]
    assert "Failed to evict stale tenant caches during startup; continuing startup" in caplog.text
    assert "invalid object-storage credentials" in caplog.text
