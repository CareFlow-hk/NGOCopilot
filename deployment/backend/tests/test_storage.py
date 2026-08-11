from __future__ import annotations

import json
from pathlib import Path
from uuid import uuid4

import pytest

from ngopilot_gateway.gcs_storage import ObjectGeneration
from ngopilot_gateway.storage import (
    RUNTIME_CACHE_MARKER,
    PlaceholderError,
    StorageService,
    parse_placeholder,
    validate_tenant_file,
)


class UploadDatabase:
    def __init__(self, row: dict[str, object] | None):
        self.row = row

    async def upload_for_placeholder(self, user_id, placeholder):
        return self.row

    async def attach_upload_to_session(self, user_id, placeholder, agent_session_id):
        self.attached = (user_id, placeholder, agent_session_id)


class CacheDatabase:
    def __init__(self, uploads=None, artifact=None, storage_objects=None):
        self.uploads = uploads or []
        self.artifact = artifact
        self.storage_objects = storage_objects
        self.artifacts: dict[str, dict[str, object]] = {}

    async def ready_uploads_for_user(self, user_id):
        return self.uploads

    async def ready_storage_objects_for_user(self, user_id):
        return self.uploads if self.storage_objects is None else self.storage_objects

    async def artifact_for_local_path(self, user_id, local_path):
        return self.artifact or self.artifacts.get(local_path)

    async def upsert_artifact(self, **values):
        self.artifacts[str(values["local_path"])] = values


class MemoryObjectStore:
    def __init__(self):
        self.objects: dict[str, bytes] = {}
        self.metadata: dict[str, dict[str, str]] = {}
        self.signed_request = None

    def upload_file(self, path, object_key, content_type, digest):
        self.objects[object_key] = Path(path).read_bytes()
        self.metadata[object_key] = {"content_type": content_type, "sha256": digest}

    def download_file(self, object_key, destination):
        Path(destination).write_bytes(self.objects[object_key])

    def object_matches(self, object_key, size, digest):
        value = self.objects.get(object_key)
        return (
            value is not None
            and len(value) == size
            and self.metadata.get(object_key, {}).get("sha256") == digest
        )

    def put_json(self, object_key, value):
        self.objects[object_key] = json.dumps(
            value, separators=(",", ":"), sort_keys=True
        ).encode()

    def read_json(self, object_key):
        value = self.objects.get(object_key)
        return json.loads(value) if value is not None else None

    def list_generations(self, prefix):
        return [
            ObjectGeneration(key=key, generation=1, is_latest=True)
            for key in self.objects
            if key.startswith(prefix)
        ]

    def delete_generations(self, generations):
        for item in generations:
            self.objects.pop(item.key, None)
            self.metadata.pop(item.key, None)

    def sign_download(self, object_key, filename, content_type, expires_in):
        self.signed_request = {
            "object_key": object_key,
            "filename": filename,
            "content_type": content_type,
            "expires_in": expires_in,
        }
        return f"https://storage.googleapis.com/{object_key}?expires={expires_in}"


class FailingUploadObjectStore(MemoryObjectStore):
    def upload_file(self, path, object_key, content_type, digest):
        raise RuntimeError("simulated GCS failure")


def test_parse_placeholder_round_trip() -> None:
    upload_id = uuid4()
    placeholder = f"ngopilot-upload://{upload_id}/case%20notes.pdf"

    assert parse_placeholder(placeholder) == (upload_id, "case notes.pdf")


@pytest.mark.parametrize(
    "placeholder",
    [
        "https://example.test/file.txt",
        "ngopilot-upload://not-a-uuid/file.txt",
        "ngopilot-upload://00000000-0000-0000-0000-000000000000/../file.txt",
    ],
)
def test_parse_placeholder_rejects_unsafe_values(placeholder: str) -> None:
    with pytest.raises(PlaceholderError):
        parse_placeholder(placeholder)


@pytest.mark.asyncio
async def test_resolve_payload_uses_only_owned_ready_upload(settings) -> None:
    user_id = uuid4()
    upload_id = uuid4()
    placeholder = f"ngopilot-upload://{upload_id}/source.xlsx"
    relative = Path("tenants") / str(user_id) / "uploads" / str(upload_id) / "source.xlsx"
    path = settings.data_root / relative
    path.parent.mkdir(parents=True)
    path.write_bytes(b"input")
    service = StorageService(
        settings,
        UploadDatabase({"status": "ready", "local_path": relative.as_posix()}),
    )

    prompt = f'Turn these forms into Excel\n\nAttachments:\n["{placeholder}"]'
    resolved = await service.resolve_payload(user_id, {"prompt": prompt})

    assert resolved == {
        "prompt": f'Turn these forms into Excel\n\nAttachments:\n["{path.resolve()}"]'
    }


@pytest.mark.asyncio
async def test_resolve_payload_attaches_upload_to_session(settings) -> None:
    user_id = uuid4()
    upload_id = uuid4()
    placeholder = f"ngopilot-upload://{upload_id}/source.xlsx"
    relative = Path("tenants") / str(user_id) / "uploads" / str(upload_id) / "source.xlsx"
    path = settings.data_root / relative
    path.parent.mkdir(parents=True)
    path.write_bytes(b"input")
    database = UploadDatabase(
        {"status": "ready", "local_path": relative.as_posix()}
    )
    service = StorageService(settings, database)

    await service.resolve_payload(
        user_id,
        {"prompt": placeholder},
        agent_session_id="session-1",
    )

    assert database.attached == (user_id, placeholder, "session-1")


def test_tenant_file_rejects_symlink_escape(settings, tmp_path: Path) -> None:
    user_id = uuid4()
    upload_root = settings.data_root / "tenants" / str(user_id) / "uploads"
    upload_root.mkdir(parents=True)
    outside = tmp_path / "outside.txt"
    outside.write_text("private", encoding="utf-8")
    (upload_root / "link.txt").symlink_to(outside)
    relative = Path("tenants") / str(user_id) / "uploads" / "link.txt"

    with pytest.raises(PlaceholderError):
        validate_tenant_file(settings.data_root, user_id, relative.as_posix(), "uploads")


@pytest.mark.asyncio
async def test_tenant_cache_round_trips_through_gcs_and_removes_old_snapshot(settings) -> None:
    user_id = uuid4()
    upload_id = uuid4()
    tenant = settings.data_root / "tenants" / str(user_id)
    session_file = tenant / "goose" / "state" / "session.json"
    database_file = tenant / "workflow" / "jobs.sqlite3"
    temporary_file = tenant / "tmp" / "large-response.txt"
    upload_relative = Path("tenants") / str(user_id) / "uploads" / str(upload_id) / "source.xlsx"
    upload_file = settings.data_root / upload_relative
    for path, content in (
        (session_file, b"session-one"),
        (database_file, b"sqlite-state"),
        (temporary_file, b"discard-me"),
        (upload_file, b"excel-input"),
    ):
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(content)

    upload_key = f"tenants/{user_id}/uploads/{upload_id}"
    object_store = MemoryObjectStore()
    object_store.objects[upload_key] = b"excel-input"
    object_store.metadata[upload_key] = {
        "content_type": "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        "sha256": StorageService._digest_file(upload_file)[0],
    }
    database = CacheDatabase(
        uploads=[
            {
                "local_path": upload_relative.as_posix(),
                "object_key": upload_key,
                "content_type": "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
                "size_bytes": len(b"excel-input"),
                "sha256": StorageService._digest_file(upload_file)[0],
            }
        ]
    )
    service = StorageService(settings, database)
    service._object_store = object_store

    await service.persist_and_evict_tenant_cache(user_id)

    assert not tenant.exists()
    pointer_key = service._snapshot_pointer_key(user_id)
    first_pointer = json.loads(object_store.objects[pointer_key])
    first_prefix = f"tenants/{user_id}/runtime-snapshots/{first_pointer['snapshot_id']}/"
    assert any(key.startswith(first_prefix) for key in object_store.objects)
    assert all(b"discard-me" not in value for value in object_store.objects.values())

    await service.restore_tenant_cache(user_id)

    assert session_file.read_bytes() == b"session-one"
    assert database_file.read_bytes() == b"sqlite-state"
    assert upload_file.read_bytes() == b"excel-input"
    assert not temporary_file.exists()
    assert (tenant / RUNTIME_CACHE_MARKER).is_file()

    session_file.write_bytes(b"session-two")
    await service.persist_and_evict_tenant_cache(user_id)

    second_pointer = json.loads(object_store.objects[pointer_key])
    assert second_pointer["snapshot_id"] != first_pointer["snapshot_id"]
    assert not any(key.startswith(first_prefix) for key in object_store.objects)


@pytest.mark.asyncio
async def test_session_object_cleanup_removes_only_exact_owned_keys(settings) -> None:
    user_id = uuid4()
    upload_key = f"tenants/{user_id}/uploads/upload-1"
    sibling_key = f"{upload_key}-sibling"
    service = StorageService(settings, CacheDatabase())
    service._object_store = MemoryObjectStore()
    service._object_store.objects.update({upload_key: b"delete", sibling_key: b"keep"})

    await service.delete_session_objects(user_id, [upload_key])

    assert upload_key not in service._object_store.objects
    assert service._object_store.objects[sibling_key] == b"keep"


@pytest.mark.asyncio
async def test_runtime_history_purge_keeps_only_current_snapshot(settings) -> None:
    user_id = uuid4()
    service = StorageService(settings, CacheDatabase())
    service._object_store = MemoryObjectStore()
    pointer_key = service._snapshot_pointer_key(user_id)
    current_id = str(uuid4())
    old_id = str(uuid4())
    current_key = f"tenants/{user_id}/runtime-snapshots/{current_id}/manifest.json"
    old_key = f"tenants/{user_id}/runtime-snapshots/{old_id}/manifest.json"
    service._object_store.objects.update(
        {
            pointer_key: json.dumps(
                {
                    "version": 1,
                    "snapshot_id": current_id,
                    "manifest_key": current_key,
                }
            ).encode(),
            current_key: b"current",
            old_key: b"contains-deleted-session",
        }
    )

    await service.purge_superseded_runtime_snapshots(user_id)

    assert pointer_key in service._object_store.objects
    assert current_key in service._object_store.objects
    assert old_key not in service._object_store.objects


@pytest.mark.asyncio
async def test_artifact_url_remains_available_after_local_cache_eviction(settings) -> None:
    user_id = uuid4()
    relative = Path("tenants") / str(user_id) / "workflow" / "exports" / "roster.xlsx"
    artifact = {
        "filename": "roster.xlsx",
        "content_type": "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        "object_key": f"tenants/{user_id}/artifacts/example",
        "size_bytes": 1234,
        "sha256": "a" * 64,
    }
    service = StorageService(settings, CacheDatabase(artifact=artifact))
    service._object_store = MemoryObjectStore()

    result = await service.artifact_download_url(user_id, relative.as_posix())

    assert result["filename"] == "roster.xlsx"
    assert result["url"].startswith("https://storage.googleapis.com/")
    assert service._object_store.signed_request == {
        "object_key": artifact["object_key"],
        "filename": "roster.xlsx",
        "content_type": artifact["content_type"],
        "expires_in": 300,
    }


@pytest.mark.asyncio
async def test_agent_text_file_path_is_mirrored_before_immediate_download(settings) -> None:
    user_id = uuid4()
    relative = Path("tenants") / str(user_id) / "generated report.xlsx"
    path = settings.data_root / relative
    path.parent.mkdir(parents=True)
    path.write_bytes(b"generated workbook")
    database = CacheDatabase()
    service = StorageService(settings, database)
    service._object_store = MemoryObjectStore()

    service.schedule_artifact_mirror(
        user_id,
        {
            "params": {
                "content": [
                    {
                        "type": "text",
                        "text": f"Generated file:\n{path}.",
                    }
                ]
            }
        },
    )
    result = await service.artifact_download_url(user_id, str(path))

    assert result["filename"] == "generated report.xlsx"
    assert relative.as_posix() in database.artifacts
    assert result["url"].startswith("https://storage.googleapis.com/")


@pytest.mark.asyncio
async def test_cache_eviction_mirrors_recoverable_local_object_to_gcs(settings) -> None:
    user_id = uuid4()
    relative = Path("tenants") / str(user_id) / "workflow" / "exports" / "care.xlsx"
    path = settings.data_root / relative
    path.parent.mkdir(parents=True)
    path.write_bytes(b"recoverable workbook")
    digest, size = StorageService._digest_file(path)
    object_key = f"tenants/{user_id}/artifacts/recoverable"
    database = CacheDatabase(
        storage_objects=[
            {
                "kind": "artifact",
                "local_path": relative.as_posix(),
                "object_key": object_key,
                "content_type": (
                    "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
                ),
                "size_bytes": size,
                "sha256": digest,
            }
        ]
    )
    service = StorageService(settings, database)
    service._object_store = MemoryObjectStore()

    await service.persist_and_evict_tenant_cache(user_id)

    assert service._object_store.objects[object_key] == b"recoverable workbook"
    assert not (settings.data_root / "tenants" / str(user_id)).exists()


@pytest.mark.asyncio
async def test_failed_snapshot_retains_local_tenant_cache(settings) -> None:
    user_id = uuid4()
    tenant = settings.data_root / "tenants" / str(user_id)
    state_file = tenant / "workflow" / "jobs.sqlite3"
    state_file.parent.mkdir(parents=True)
    state_file.write_bytes(b"must-survive")
    service = StorageService(settings, CacheDatabase())
    service._object_store = FailingUploadObjectStore()

    with pytest.raises(RuntimeError, match="simulated GCS failure"):
        await service.persist_and_evict_tenant_cache(user_id)

    assert state_file.read_bytes() == b"must-survive"
    assert service._snapshot_pointer_key(user_id) not in service._object_store.objects
