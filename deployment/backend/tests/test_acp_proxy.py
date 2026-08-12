from __future__ import annotations

import asyncio
import json
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock
from uuid import uuid4

import pytest
from fastapi import WebSocketDisconnect

from ngopilot_gateway import acp_proxy
from ngopilot_gateway.acp_proxy import (
    AcpRecorder,
    browser_message,
    extract_jobs,
    isolate_client_request,
    proxy_websocket,
)


class RecordingDatabase:
    def __init__(self):
        self.calls: list[tuple[object, ...]] = []

    def __getattr__(self, name: str):
        async def record(*args, **kwargs):
            self.calls.append((name, *args, kwargs))

        return record


class TestWebSocket:
    __test__ = False

    def __init__(self, *, accept_error: Exception | None = None):
        self.accepted = False
        self.accept_error = accept_error
        self.app = SimpleNamespace(
            state=SimpleNamespace(
                session_deletion=SimpleNamespace(delete=AsyncMock()),
            )
        )

    async def accept(self) -> None:
        if self.accept_error is not None:
            raise self.accept_error
        self.accepted = True

    async def receive_text(self) -> str:
        raise WebSocketDisconnect(code=1000)


class BlockingUpstream:
    async def __aenter__(self):
        return self

    async def __aexit__(self, exc_type, exc, traceback) -> None:
        return None

    async def send(self, message: str) -> None:
        return None

    def __aiter__(self):
        async def messages():
            await asyncio.Future()
            yield ""

        return messages()


@pytest.mark.asyncio
async def test_proxy_accepts_browser_before_waiting_for_tenant_startup(settings) -> None:
    websocket = TestWebSocket()
    processes = SimpleNamespace(release=AsyncMock())

    async def fail_acquire(user_id):
        assert websocket.accepted is True
        raise RuntimeError("startup failed")

    processes.acquire = AsyncMock(side_effect=fail_acquire)

    with pytest.raises(RuntimeError, match="startup failed"):
        await proxy_websocket(
            websocket,
            uuid4(),
            settings,
            RecordingDatabase(),
            processes,
            SimpleNamespace(),
        )

    processes.release.assert_not_awaited()


@pytest.mark.asyncio
async def test_proxy_returns_cleanly_when_browser_disconnects_during_accept(settings) -> None:
    websocket = TestWebSocket(accept_error=OSError("client disconnected"))
    processes = SimpleNamespace(acquire=AsyncMock(), release=AsyncMock())

    await proxy_websocket(
        websocket,
        uuid4(),
        settings,
        RecordingDatabase(),
        processes,
        SimpleNamespace(),
    )

    processes.acquire.assert_not_awaited()
    processes.release.assert_not_awaited()


@pytest.mark.asyncio
async def test_proxy_releases_successful_acquire_once_after_client_disconnect(
    settings, monkeypatch
) -> None:
    websocket = TestWebSocket()
    managed = SimpleNamespace(
        websocket_url="ws://127.0.0.1:1234/acp",
        secret="secret",
        tenant_root=Path("/data/tenants/test-user"),
    )
    processes = SimpleNamespace(acquire=AsyncMock(return_value=managed), release=AsyncMock())
    monkeypatch.setattr(acp_proxy, "connect", lambda *args, **kwargs: BlockingUpstream())

    await proxy_websocket(
        websocket,
        uuid4(),
        settings,
        RecordingDatabase(),
        processes,
        SimpleNamespace(),
    )

    processes.acquire.assert_awaited_once()
    processes.release.assert_awaited_once()


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("method", "params", "expected"),
    [
        (
            "_goose/unstable/session/rename",
            {"sessionId": "session-1", "title": "Renamed"},
            "rename_chat_session",
        ),
        (
            "_goose/unstable/session/archive",
            {"sessionId": "session-1"},
            "archive_chat_session",
        ),
        ("session/delete", {"sessionId": "session-1"}, "delete_chat_session"),
    ],
)
async def test_successful_session_mutations_are_projected(
    settings, method: str, params: dict[str, str], expected: str
) -> None:
    database = RecordingDatabase()
    recorder = AcpRecorder(database, settings, uuid4())

    await recorder.client_message({"jsonrpc": "2.0", "id": 7, "method": method, "params": params})
    await recorder.agent_message({"jsonrpc": "2.0", "id": 7, "result": {}})

    assert expected in [str(call[0]) for call in database.calls]


@pytest.mark.asyncio
async def test_session_deletion_uses_cloud_cleanup_callback(settings) -> None:
    database = RecordingDatabase()
    user_id = uuid4()
    deleted: list[tuple[object, str]] = []

    async def delete_session(owner, session_id):
        deleted.append((owner, session_id))

    recorder = AcpRecorder(
        database,
        settings,
        user_id,
        delete_session=delete_session,
    )
    await recorder.client_message(
        {
            "jsonrpc": "2.0",
            "id": 8,
            "method": "session/delete",
            "params": {"sessionId": "session-1"},
        }
    )
    await recorder.agent_message({"jsonrpc": "2.0", "id": 8, "result": {}})

    assert deleted == [(user_id, "session-1")]
    assert "delete_chat_session" not in [str(call[0]) for call in database.calls]


@pytest.mark.asyncio
async def test_failed_agent_deletion_does_not_run_cloud_cleanup(settings) -> None:
    database = RecordingDatabase()
    deleted: list[str] = []

    async def delete_session(owner, session_id):
        deleted.append(session_id)

    recorder = AcpRecorder(
        database,
        settings,
        uuid4(),
        delete_session=delete_session,
    )
    await recorder.client_message(
        {
            "jsonrpc": "2.0",
            "id": 9,
            "method": "session/delete",
            "params": {"sessionId": "session-1"},
        }
    )
    await recorder.agent_message(
        {"jsonrpc": "2.0", "id": 9, "error": {"code": -32603, "message": "failed"}}
    )

    assert deleted == []


def test_extract_jobs_finds_nested_tool_payload() -> None:
    value = {"content": '{"job_id":"job-123","tool_name":"roster_copilot","state":"ready"}'}

    assert extract_jobs(value) == [
        (
            "job-123",
            "roster_copilot",
            {"job_id": "job-123", "tool_name": "roster_copilot", "state": "ready"},
        )
    ]


def test_oversized_tool_output_is_compacted_for_browser() -> None:
    message = {
        "jsonrpc": "2.0",
        "method": "session/update",
        "params": {
            "sessionId": "session-1",
            "update": {
                "sessionUpdate": "tool_call_update",
                "toolCallId": "call-1",
                "status": "completed",
                "content": [{"type": "content", "content": {"type": "text", "text": "Done"}}],
                "rawOutput": {"result": "x" * (2 * 1024 * 1024)},
            },
        },
    }
    raw = json.dumps(message)

    compacted = json.loads(browser_message(raw, message))

    assert compacted["params"]["update"]["content"] == message["params"]["update"]["content"]
    assert compacted["params"]["update"]["rawOutput"] == {
        "truncated": True,
        "message": "Oversized tool output omitted from the browser stream.",
    }
    assert len(json.dumps(compacted).encode("utf-8")) < 1024 * 1024


@pytest.mark.parametrize("output_key", ["rawOutput", "raw_output"])
def test_oversized_flat_tool_output_is_compacted_for_browser(output_key: str) -> None:
    message = {
        "jsonrpc": "2.0",
        "method": "session/update",
        "params": {
            "sessionId": "session-1",
            "sessionUpdate": "tool_call_update",
            "toolCallId": "call-1",
            "status": "completed",
            "content": [{"type": "content", "content": {"type": "text", "text": "Done"}}],
            output_key: {"result": "x" * (2 * 1024 * 1024)},
        },
    }
    raw = json.dumps(message)

    compacted = json.loads(browser_message(raw, message))

    assert compacted["params"]["sessionId"] == "session-1"
    assert compacted["params"]["content"] == message["params"]["content"]
    assert compacted["params"][output_key] == {
        "truncated": True,
        "message": "Oversized tool output omitted from the browser stream.",
    }
    assert "update" not in compacted["params"]
    assert len(json.dumps(compacted).encode("utf-8")) < 1024 * 1024


def test_small_agent_message_is_forwarded_unchanged() -> None:
    message = {"jsonrpc": "2.0", "method": "session/update", "params": {"update": {}}}
    raw = json.dumps(message)

    assert browser_message(raw, message) is raw


@pytest.mark.parametrize("method", ["session/new", "session/load"])
def test_session_requests_are_confined_to_tenant_root(method: str) -> None:
    original = {
        "jsonrpc": "2.0",
        "id": 1,
        "method": method,
        "params": {
            "cwd": "/data/tenants/another-user",
            "mcpServers": [{"name": "untrusted"}],
            "sessionId": "session-1",
        },
    }

    isolated = isolate_client_request(original, Path("/data/tenants/current-user"))

    assert isolated["params"] == {
        "cwd": "/data/tenants/current-user",
        "mcpServers": [],
        "sessionId": "session-1",
    }
    assert original["params"]["cwd"] == "/data/tenants/another-user"


def test_working_directory_updates_are_confined_to_tenant_root() -> None:
    message = {
        "method": "_goose/unstable/session/working-dir/update",
        "params": {"sessionId": "session-1", "workingDir": "/tmp"},
    }

    isolated = isolate_client_request(message, Path("/data/tenants/current-user"))

    assert isolated["params"]["workingDir"] == "/data/tenants/current-user"
