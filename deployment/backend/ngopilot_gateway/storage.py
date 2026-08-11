"""Private GCS persistence and safe tenant-local cache management."""

from __future__ import annotations

import asyncio
import hashlib
import json
import logging
import mimetypes
import re
import shutil
from collections.abc import Iterable, Mapping
from pathlib import Path
from typing import Any, Iterator
from urllib.parse import unquote, urlsplit
from uuid import NAMESPACE_URL, UUID, uuid4, uuid5

import aiofiles
from fastapi import HTTPException, UploadFile, status

from .config import Settings
from .db import Database
from .gcs_storage import GcsObjectStore

logger = logging.getLogger(__name__)

PLACEHOLDER_PATTERN = re.compile(
    r"ngopilot-upload://[0-9a-fA-F]{8}-[0-9a-fA-F]{4}-"
    r"[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{12}/[^\s\"<>]+"
)
SAFE_FILENAME_PATTERN = re.compile(r"[^A-Za-z0-9._-]+")
TRAILING_PATH_PUNCTUATION = "),.;:!?"
RUNTIME_CACHE_AREAS = ("goose", "workflow")
RUNTIME_CACHE_MARKER = ".ngopilot-cache-ready"
RUNTIME_SNAPSHOT_VERSION = 1
SNAPSHOT_TRANSFER_CONCURRENCY = 8


class PlaceholderError(ValueError):
    pass


def parse_placeholder(value: str) -> tuple[UUID, str]:
    parsed = urlsplit(value)
    if parsed.scheme != "ngopilot-upload" or not parsed.netloc or parsed.query or parsed.fragment:
        raise PlaceholderError("Invalid upload placeholder")
    try:
        upload_id = UUID(parsed.netloc)
    except ValueError as error:
        raise PlaceholderError("Invalid upload identifier") from error
    encoded_name = parsed.path.removeprefix("/")
    if not encoded_name or "/" in encoded_name:
        raise PlaceholderError("Invalid upload filename")
    filename = unquote(encoded_name)
    if not filename or filename in {".", ".."} or Path(filename).name != filename:
        raise PlaceholderError("Invalid upload filename")
    return upload_id, filename


def safe_filename(value: str) -> str:
    cleaned = SAFE_FILENAME_PATTERN.sub("_", Path(value).name).strip("._")
    if not cleaned:
        cleaned = "upload"
    suffix = Path(value).suffix
    if suffix and not cleaned.endswith(suffix) and len(suffix) <= 16:
        cleaned += SAFE_FILENAME_PATTERN.sub("_", suffix)
    return cleaned[:180]


def _has_symlink_component(root: Path, relative: Path) -> bool:
    current = root
    for part in relative.parts:
        current = current / part
        if current.is_symlink():
            return True
    return False


def validate_tenant_file(
    data_root: Path,
    user_id: UUID,
    local_path: str,
    area: str,
) -> Path:
    relative = Path(local_path)
    if relative.is_absolute() or ".." in relative.parts or not relative.parts:
        raise PlaceholderError("Stored upload path is invalid")
    data_root_resolved = data_root.resolve()
    if _has_symlink_component(data_root_resolved, relative):
        raise PlaceholderError("Stored upload path contains a symbolic link")
    candidate = (data_root_resolved / relative).resolve(strict=True)
    allowed = (data_root_resolved / "tenants" / str(user_id) / area).resolve(strict=True)
    if not candidate.is_relative_to(allowed) or not candidate.is_file():
        raise PlaceholderError("Stored upload path is outside the tenant directory")
    return candidate


def tenant_relative_path(
    user_id: UUID,
    local_path: str,
    area: str,
) -> Path:
    relative = Path(local_path)
    expected = Path("tenants") / str(user_id) / area
    if (
        relative.is_absolute()
        or ".." in relative.parts
        or not relative.is_relative_to(expected)
        or relative == expected
    ):
        raise PlaceholderError("Stored tenant path is invalid")
    return relative


def tenant_owned_path(data_root: Path, user_id: UUID, local_path: str) -> Path:
    relative = Path(local_path)
    tenant_relative = Path("tenants") / str(user_id)
    if (
        relative.is_absolute()
        or ".." in relative.parts
        or not relative.is_relative_to(tenant_relative)
        or relative == tenant_relative
    ):
        raise PlaceholderError("Stored session path is outside the tenant directory")
    data_root_resolved = data_root.resolve()
    if _has_symlink_component(data_root_resolved, relative):
        raise PlaceholderError("Stored session path contains a symbolic link")
    return data_root_resolved / relative


def runtime_relative_path(value: str) -> Path:
    relative = Path(value)
    if (
        relative.is_absolute()
        or ".." in relative.parts
        or len(relative.parts) < 2
        or relative.parts[0] not in RUNTIME_CACHE_AREAS
    ):
        raise PlaceholderError("Stored runtime snapshot path is invalid")
    return relative


def iter_mappings(value: Any, *, parse_json_strings: bool = True) -> Iterator[dict[str, Any]]:
    if isinstance(value, dict):
        yield value
        for child in value.values():
            yield from iter_mappings(child, parse_json_strings=parse_json_strings)
    elif isinstance(value, list):
        for child in value:
            yield from iter_mappings(child, parse_json_strings=parse_json_strings)
    elif parse_json_strings and isinstance(value, str) and len(value) <= 1_000_000:
        stripped = value.lstrip()
        if stripped.startswith(("{", "[")):
            try:
                decoded = json.loads(value)
            except (json.JSONDecodeError, ValueError):
                return
            yield from iter_mappings(decoded, parse_json_strings=False)


def iter_strings(value: Any) -> Iterator[str]:
    if isinstance(value, str):
        yield value
    elif isinstance(value, dict):
        for child in value.values():
            yield from iter_strings(child)
    elif isinstance(value, list):
        for child in value:
            yield from iter_strings(child)


class StorageService:
    def __init__(self, settings: Settings, db: Database):
        self.settings = settings
        self.db = db
        self._tasks: set[asyncio.Task[None]] = set()
        self._task_users: dict[asyncio.Task[None], UUID] = {}
        self._cache_locks: dict[UUID, asyncio.Lock] = {}
        self._object_store = GcsObjectStore(settings) if settings.gcs_configured else None

    async def close(self) -> None:
        if not self._tasks:
            return
        await asyncio.gather(*list(self._tasks), return_exceptions=True)

    async def health_check(self) -> bool:
        if self._object_store is None:
            return False
        try:
            await asyncio.to_thread(self._object_store.health_check)
        except Exception as error:
            logger.warning("GCS readiness check failed: %s", type(error).__name__)
            return False
        return True

    def _cache_lock(self, user_id: UUID) -> asyncio.Lock:
        lock = self._cache_locks.get(user_id)
        if lock is None:
            lock = asyncio.Lock()
            self._cache_locks[user_id] = lock
        return lock

    async def store_upload(
        self,
        user_id: UUID,
        upload_id_value: str,
        placeholder: str,
        file: UploadFile,
    ) -> dict[str, Any]:
        if self._object_store is None:
            raise HTTPException(
                status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
                detail="Object storage is not configured",
            )
        try:
            upload_id = UUID(upload_id_value)
            placeholder_id, placeholder_filename = parse_placeholder(placeholder)
        except ValueError as error:
            raise HTTPException(
                status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail=str(error)
            ) from error
        if upload_id != placeholder_id:
            raise HTTPException(
                status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
                detail="Upload identifier does not match placeholder",
            )
        original_filename = Path(file.filename or "").name
        if not original_filename or original_filename != placeholder_filename:
            raise HTTPException(
                status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
                detail="Upload filename does not match placeholder",
            )

        content_type = file.content_type or "application/octet-stream"
        try:
            await self.db.create_upload(
                upload_id, user_id, original_filename, content_type, placeholder
            )
        except Exception as error:
            # A client UUID is an idempotency key; overwriting another object is never allowed.
            if error.__class__.__name__.endswith("UniqueViolationError"):
                raise HTTPException(
                    status_code=status.HTTP_409_CONFLICT, detail="Upload already exists"
                ) from error
            raise

        relative = (
            Path("tenants")
            / str(user_id)
            / "uploads"
            / str(upload_id)
            / safe_filename(original_filename)
        )
        destination = self.settings.data_root / relative
        digest = hashlib.sha256()
        size = 0
        try:
            async with self._cache_lock(user_id):
                destination.parent.mkdir(parents=True, exist_ok=False, mode=0o700)
                try:
                    async with aiofiles.open(destination, "xb") as output:
                        while chunk := await file.read(1024 * 1024):
                            size += len(chunk)
                            if size > self.settings.max_upload_bytes:
                                raise HTTPException(
                                    status_code=status.HTTP_413_REQUEST_ENTITY_TOO_LARGE,
                                    detail="Upload exceeds the configured size limit",
                                )
                            digest.update(chunk)
                            await output.write(chunk)
                    destination.chmod(0o600)
                    object_key = f"tenants/{user_id}/uploads/{upload_id}"
                    await self._upload_private(
                        destination, object_key, content_type, digest.hexdigest()
                    )
                    await self.db.finish_upload(
                        upload_id,
                        user_id,
                        size_bytes=size,
                        sha256=digest.hexdigest(),
                        local_path=relative.as_posix(),
                        object_key=object_key,
                    )
                except Exception:
                    if destination.exists():
                        destination.unlink()
                    raise
        except Exception as error:
            await self.db.fail_upload(upload_id, user_id, type(error).__name__)
            raise
        finally:
            await file.close()

        return {
            "id": str(upload_id),
            "placeholder": placeholder,
            "filename": original_filename,
            "content_type": content_type,
            "size_bytes": size,
            "sha256": digest.hexdigest(),
        }

    async def resolve_placeholder(
        self,
        user_id: UUID,
        placeholder: str,
        *,
        agent_session_id: str | None = None,
    ) -> str:
        parse_placeholder(placeholder)
        deadline = asyncio.get_running_loop().time() + self.settings.upload_resolve_timeout_seconds
        while True:
            row = await self.db.upload_for_placeholder(user_id, placeholder)
            if row is not None and row["status"] == "ready" and row["local_path"]:
                if agent_session_id is not None:
                    await self.db.attach_upload_to_session(
                        user_id, placeholder, agent_session_id
                    )
                try:
                    path = validate_tenant_file(
                        self.settings.data_root, user_id, row["local_path"], "uploads"
                    )
                except (FileNotFoundError, OSError):
                    async with self._cache_lock(user_id):
                        await self._restore_upload(user_id, row)
                    path = validate_tenant_file(
                        self.settings.data_root, user_id, row["local_path"], "uploads"
                    )
                return str(path)
            if row is not None and row["status"] == "failed":
                raise PlaceholderError("Upload failed before the prompt was sent")
            if asyncio.get_running_loop().time() >= deadline:
                raise PlaceholderError("Upload is not ready; try sending the prompt again")
            await asyncio.sleep(0.1)

    async def resolve_payload(
        self,
        user_id: UUID,
        value: Any,
        *,
        agent_session_id: str | None = None,
    ) -> Any:
        placeholders: set[str] = set()

        def collect(item: Any) -> None:
            if isinstance(item, str):
                placeholders.update(PLACEHOLDER_PATTERN.findall(item))
            elif isinstance(item, dict):
                for child in item.values():
                    collect(child)
            elif isinstance(item, list):
                for child in item:
                    collect(child)

        collect(value)
        if not placeholders:
            return value
        replacements = {
            item: await self.resolve_placeholder(
                user_id, item, agent_session_id=agent_session_id
            )
            for item in placeholders
        }

        def replace(item: Any) -> Any:
            if isinstance(item, str):
                for placeholder, path in replacements.items():
                    item = item.replace(placeholder, path)
                return item
            if isinstance(item, dict):
                return {key: replace(child) for key, child in item.items()}
            if isinstance(item, list):
                return [replace(child) for child in item]
            return item

        return replace(value)

    def schedule_artifact_mirror(self, user_id: UUID, payload: Any) -> None:
        task = asyncio.create_task(
            self._mirror_artifacts(user_id, payload), name=f"artifact-mirror-{user_id}"
        )
        self._tasks.add(task)
        self._task_users[task] = user_id
        task.add_done_callback(self._artifact_task_done)

    def _artifact_task_done(self, task: asyncio.Task[None]) -> None:
        self._tasks.discard(task)
        self._task_users.pop(task, None)
        if not task.cancelled() and task.exception() is not None:
            logger.error("Artifact mirror failed: %s", type(task.exception()).__name__)

    async def artifact_download_url(self, user_id: UUID, local_path: str) -> dict[str, Any]:
        if self._object_store is None:
            raise HTTPException(
                status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
                detail="Object storage is not configured",
            )

        await self._wait_for_artifact_tasks(user_id)

        try:
            supplied = Path(local_path)
            if supplied.is_absolute():
                relative = supplied.relative_to(self.settings.data_root)
            else:
                relative = supplied
            expected = Path("tenants") / str(user_id)
            if (
                relative.is_absolute()
                or ".." in relative.parts
                or not relative.is_relative_to(expected)
                or relative == expected
            ):
                raise PlaceholderError("Stored artifact path is invalid")
        except (PlaceholderError, ValueError) as error:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND, detail="Artifact not found"
            ) from error

        row = await self.db.artifact_for_local_path(user_id, relative.as_posix())
        if row is None:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="Artifact is not available yet",
            )

        filename = safe_filename(row["filename"])
        url = await asyncio.to_thread(
            self._object_store.sign_download,
            row["object_key"],
            filename,
            row["content_type"],
            300,
        )
        return {
            "url": url,
            "filename": row["filename"],
            "content_type": row["content_type"],
            "size_bytes": row["size_bytes"],
            "sha256": row["sha256"],
            "expires_in": 300,
        }

    async def _mirror_artifacts(self, user_id: UUID, payload: Any) -> None:
        if self._object_store is None:
            return
        seen: set[Path] = set()
        raw_paths: set[str] = set()
        job_id: str | None = None
        agent_session_id: str | None = None
        for mapping in iter_mappings(payload):
            candidate_job_id = mapping.get("job_id")
            if isinstance(candidate_job_id, str) and len(candidate_job_id) <= 96:
                job_id = candidate_job_id
            candidate_session_id = mapping.get("sessionId") or mapping.get("session_id")
            if (
                isinstance(candidate_session_id, str)
                and 0 < len(candidate_session_id) <= 256
            ):
                agent_session_id = candidate_session_id
            for key in ("path", "output_path", "artifact_path"):
                raw_path = mapping.get(key)
                if isinstance(raw_path, str) and raw_path.startswith("/"):
                    raw_paths.add(raw_path)

        tenant_root = (self.settings.data_root / "tenants" / str(user_id)).resolve()
        path_pattern = re.compile(
            re.escape(str(tenant_root)) + r"/[^\r\n\"'`<>\[\]{}|\\]+"
        )
        for text in iter_strings(payload):
            stripped = text.lstrip()
            if stripped.startswith(("{", "[")):
                try:
                    json.loads(text)
                except (json.JSONDecodeError, ValueError):
                    pass
                else:
                    continue
            raw_paths.update(
                match.group(0).rstrip(TRAILING_PATH_PUNCTUATION)
                for match in path_pattern.finditer(text)
            )

        for raw_path in raw_paths:
            try:
                path = Path(raw_path).resolve(strict=True)
            except (FileNotFoundError, OSError):
                continue
            if path in seen or not path.is_file() or not path.is_relative_to(tenant_root):
                continue
            relative = path.relative_to(self.settings.data_root.resolve())
            if _has_symlink_component(self.settings.data_root.resolve(), relative):
                continue
            seen.add(path)
            digest, size = await asyncio.to_thread(self._digest_file, path)
            content_type = mimetypes.guess_type(path.name)[0] or "application/octet-stream"
            artifact_id = uuid5(NAMESPACE_URL, f"{user_id}:{relative.as_posix()}")
            object_key = f"tenants/{user_id}/artifacts/{artifact_id}"
            await self._upload_private(path, object_key, content_type, digest)
            await self.db.upsert_artifact(
                artifact_id=artifact_id,
                user_id=user_id,
                job_id=job_id,
                agent_session_id=agent_session_id,
                filename=path.name,
                content_type=content_type,
                size_bytes=size,
                sha256=digest,
                local_path=relative.as_posix(),
                object_key=object_key,
            )

    async def restore_tenant_cache(self, user_id: UUID) -> None:
        if self._object_store is None:
            return
        async with self._cache_lock(user_id):
            tenant_root = self.settings.data_root / "tenants" / str(user_id)
            marker = tenant_root / RUNTIME_CACHE_MARKER
            if marker.is_file():
                return

            tenant_root.mkdir(parents=True, exist_ok=True, mode=0o700)
            try:
                for area in RUNTIME_CACHE_AREAS:
                    cached_area = tenant_root / area
                    if cached_area.is_symlink():
                        cached_area.unlink()
                    elif cached_area.exists():
                        await asyncio.to_thread(shutil.rmtree, cached_area)

                pointer = await self._snapshot_json(self._snapshot_pointer_key(user_id))
                snapshot_id = "new"
                if pointer is not None:
                    snapshot_id = self._snapshot_id(pointer)
                    manifest_key = pointer.get("manifest_key")
                    expected_manifest_key = (
                        f"tenants/{user_id}/runtime-snapshots/{snapshot_id}/manifest.json"
                    )
                    if manifest_key != expected_manifest_key:
                        raise RuntimeError("Runtime snapshot pointer is invalid")
                    manifest = await self._snapshot_json(manifest_key)
                    if manifest is None:
                        raise RuntimeError("Runtime snapshot manifest is missing")
                    await self._restore_runtime_manifest(user_id, tenant_root, manifest)

                for row in await self.db.ready_uploads_for_user(user_id):
                    await self._restore_upload(user_id, row)

                marker.write_text(snapshot_id + "\n", encoding="utf-8")
                marker.chmod(0o600)
            except Exception:
                marker.unlink(missing_ok=True)
                for area in RUNTIME_CACHE_AREAS:
                    cached_area = tenant_root / area
                    if cached_area.is_symlink():
                        cached_area.unlink()
                    elif cached_area.exists():
                        await asyncio.to_thread(shutil.rmtree, cached_area)
                raise

    async def persist_and_evict_tenant_cache(self, user_id: UUID) -> None:
        if self._object_store is None:
            return
        await self._wait_for_artifact_tasks(user_id)
        async with self._cache_lock(user_id):
            tenant_root = self.settings.data_root / "tenants" / str(user_id)
            if not tenant_root.is_dir():
                return

            await self._mirror_local_storage_objects(user_id)
            old_pointer = await self._snapshot_json(self._snapshot_pointer_key(user_id))
            old_snapshot_id = self._snapshot_id(old_pointer) if old_pointer is not None else None
            snapshot_id = str(uuid4())
            prefix = f"tenants/{user_id}/runtime-snapshots/{snapshot_id}"
            try:
                entries = await self._upload_runtime_snapshot(tenant_root, prefix)
                manifest_key = f"{prefix}/manifest.json"
                manifest = {
                    "version": RUNTIME_SNAPSHOT_VERSION,
                    "snapshot_id": snapshot_id,
                    "user_id": str(user_id),
                    "files": entries,
                }
                await self._put_snapshot_json(manifest_key, manifest)
            except Exception:
                try:
                    await self._delete_snapshot_prefix(user_id, snapshot_id)
                except Exception:
                    logger.exception(
                        "Failed to delete incomplete runtime snapshot for user %s",
                        user_id,
                    )
                raise

            # Do not delete the new prefix if this call has an ambiguous network failure:
            # GCS may have committed the pointer even when the response did not arrive.
            await self._put_snapshot_json(
                self._snapshot_pointer_key(user_id),
                {
                    "version": RUNTIME_SNAPSHOT_VERSION,
                    "snapshot_id": snapshot_id,
                    "manifest_key": manifest_key,
                },
            )

            await asyncio.to_thread(shutil.rmtree, tenant_root)
            logger.info(
                "Committed tenant runtime snapshot %s with %d files and evicted local cache",
                snapshot_id,
                len(entries),
            )

            if old_snapshot_id is not None and old_snapshot_id != snapshot_id:
                try:
                    await self._delete_snapshot_prefix(user_id, old_snapshot_id)
                except Exception:
                    logger.exception(
                        "Failed to delete superseded runtime snapshot for user %s",
                        user_id,
                    )
            try:
                await self._delete_noncurrent_pointer_versions(user_id)
            except Exception:
                logger.exception(
                    "Failed to delete superseded runtime pointer versions for user %s",
                    user_id,
                )

    async def evict_stale_tenant_caches(
        self, excluded_user_ids: set[UUID] | None = None
    ) -> None:
        if self._object_store is None:
            return
        excluded = excluded_user_ids or set()
        tenants_root = self.settings.data_root / "tenants"
        if not tenants_root.is_dir():
            return
        for path in sorted(tenants_root.iterdir()):
            if not path.is_dir():
                continue
            try:
                user_id = UUID(path.name)
            except ValueError:
                logger.warning("Ignoring unexpected data-root directory: %s", path.name)
                continue
            if user_id in excluded:
                continue
            await self.persist_and_evict_tenant_cache(user_id)

    async def delete_session_objects(
        self, user_id: UUID, objects: Iterable[Mapping[str, Any]]
    ) -> None:
        items = list(objects)
        await self.delete_session_local_objects(user_id, items)
        await self.delete_session_object_versions(user_id, items)

    async def delete_session_local_objects(
        self, user_id: UUID, objects: Iterable[Mapping[str, Any]]
    ) -> None:
        local_paths: set[str] = set()
        for item in objects:
            local_path = item.get("local_path")
            if local_path is not None:
                if not isinstance(local_path, str):
                    raise RuntimeError("Session local path is invalid")
                local_paths.add(local_path)
        await self._delete_session_local_files(user_id, local_paths)

    async def delete_session_object_versions(
        self, user_id: UUID, objects: Iterable[Mapping[str, Any]]
    ) -> None:
        object_keys: set[str] = set()
        for item in objects:
            object_key = item.get("object_key")
            if object_key is not None:
                if not isinstance(object_key, str):
                    raise RuntimeError("Session object key is invalid")
                object_keys.add(object_key)

        if self._object_store is None:
            return
        allowed_prefixes = (
            f"tenants/{user_id}/uploads/",
            f"tenants/{user_id}/artifacts/",
        )
        for object_key in sorted(object_keys):
            if not object_key.startswith(allowed_prefixes):
                raise RuntimeError("Session object key is outside the tenant storage prefixes")
            await self._delete_object_versions(object_key, exact_key=object_key)

    async def _delete_session_local_files(self, user_id: UUID, local_paths: Iterable[str]) -> None:
        tenant_root = (self.settings.data_root / "tenants" / str(user_id)).resolve()
        async with self._cache_lock(user_id):
            for local_path in sorted(set(local_paths)):
                path = tenant_owned_path(self.settings.data_root, user_id, local_path)
                if path.is_symlink():
                    raise RuntimeError("Session local path is a symbolic link")
                if path.exists() and not path.is_file():
                    raise RuntimeError("Session local path is not a file")
                path.unlink(missing_ok=True)

                parent = path.parent
                while parent != tenant_root and parent.is_relative_to(tenant_root):
                    try:
                        parent.rmdir()
                    except (FileNotFoundError, OSError):
                        break
                    parent = parent.parent

    async def purge_superseded_runtime_snapshots(self, user_id: UUID) -> None:
        """Remove every runtime snapshot/version except the current committed snapshot."""
        if self._object_store is None:
            return
        pointer_key = self._snapshot_pointer_key(user_id)
        pointer = await self._snapshot_json(pointer_key)
        if pointer is None:
            return
        snapshot_id = self._snapshot_id(pointer)
        current_prefix = f"tenants/{user_id}/runtime-snapshots/{snapshot_id}/"
        runtime_prefix = f"tenants/{user_id}/runtime-snapshots/"
        assert self._object_store is not None
        generations = await asyncio.to_thread(
            self._object_store.list_generations, runtime_prefix
        )
        obsolete = [
            item
            for item in generations
            if not item.key.startswith(current_prefix)
            and not (
                item.key == pointer_key
                and item.is_latest
            )
        ]
        if obsolete:
            await asyncio.to_thread(self._object_store.delete_generations, obsolete)

    async def _mirror_local_storage_objects(self, user_id: UUID) -> None:
        """Preserve verified local files before removing a tenant cache."""
        assert self._object_store is not None
        data_root = self.settings.data_root.resolve()
        tenant_prefix = Path("tenants") / str(user_id)
        for row in await self.db.ready_storage_objects_for_user(user_id):
            local_path = row["local_path"]
            object_key = row["object_key"]
            content_type = row["content_type"]
            size = row["size_bytes"]
            digest = row["sha256"]
            if (
                not isinstance(local_path, str)
                or not isinstance(object_key, str)
                or not isinstance(content_type, str)
                or not isinstance(size, int)
                or size < 0
                or not isinstance(digest, str)
                or not re.fullmatch(r"[0-9a-f]{64}", digest)
            ):
                raise RuntimeError("Stored object metadata is incomplete")
            relative = Path(local_path)
            if (
                relative.is_absolute()
                or ".." in relative.parts
                or not relative.is_relative_to(tenant_prefix)
                or relative == tenant_prefix
            ):
                raise RuntimeError("Stored object cache path is invalid")
            if await asyncio.to_thread(
                self._object_store.object_matches, object_key, size, digest
            ):
                continue
            path = data_root / relative
            if not path.is_file():
                logger.warning("Local copy is unavailable for GCS object %s", object_key)
                continue
            if _has_symlink_component(data_root, relative):
                raise RuntimeError("Stored object cache path contains a symbolic link")
            actual_digest, actual_size = await asyncio.to_thread(self._digest_file, path)
            if actual_size != size or actual_digest != digest:
                raise RuntimeError("Local object failed integrity verification before GCS upload")
            await self._upload_private(path, object_key, content_type, digest)

    async def _wait_for_artifact_tasks(self, user_id: UUID) -> None:
        tasks = [task for task, owner in self._task_users.items() if owner == user_id]
        if tasks:
            await asyncio.gather(*tasks, return_exceptions=True)

    async def _upload_runtime_snapshot(
        self, tenant_root: Path, prefix: str
    ) -> list[dict[str, Any]]:
        files: list[tuple[Path, Path]] = []
        for area in RUNTIME_CACHE_AREAS:
            root = tenant_root / area
            if not root.is_dir():
                continue
            for path in root.rglob("*"):
                if path.is_symlink() or not path.is_file():
                    continue
                relative = path.relative_to(tenant_root)
                files.append((path, relative))

        semaphore = asyncio.Semaphore(SNAPSHOT_TRANSFER_CONCURRENCY)

        async def upload(index: int, path: Path, relative: Path) -> dict[str, Any]:
            async with semaphore:
                digest, size = await asyncio.to_thread(self._digest_file, path)
                object_key = f"{prefix}/objects/{index:08d}-{uuid4()}"
                content_type = mimetypes.guess_type(path.name)[0] or "application/octet-stream"
                await self._upload_private(path, object_key, content_type, digest)
                return {
                    "path": relative.as_posix(),
                    "object_key": object_key,
                    "size_bytes": size,
                    "sha256": digest,
                    "mode": path.stat().st_mode & 0o700,
                }

        results = await asyncio.gather(
            *(upload(index, path, relative) for index, (path, relative) in enumerate(files)),
            return_exceptions=True,
        )
        entries: list[dict[str, Any]] = []
        for result in results:
            if isinstance(result, BaseException):
                raise result
            entries.append(result)
        return entries

    async def _restore_runtime_manifest(
        self, user_id: UUID, tenant_root: Path, manifest: dict[str, Any]
    ) -> None:
        if (
            manifest.get("version") != RUNTIME_SNAPSHOT_VERSION
            or manifest.get("user_id") != str(user_id)
            or not isinstance(manifest.get("files"), list)
        ):
            raise RuntimeError("Runtime snapshot manifest is invalid")
        snapshot_id = self._snapshot_id(manifest)
        object_prefix = f"tenants/{user_id}/runtime-snapshots/{snapshot_id}/objects/"
        seen_paths: set[Path] = set()

        semaphore = asyncio.Semaphore(SNAPSHOT_TRANSFER_CONCURRENCY)

        async def restore(entry: Any) -> None:
            if not isinstance(entry, dict):
                raise RuntimeError("Runtime snapshot entry is invalid")
            relative = runtime_relative_path(str(entry.get("path", "")))
            object_key = entry.get("object_key")
            size = entry.get("size_bytes")
            digest = entry.get("sha256")
            mode = entry.get("mode", 0o600)
            if (
                not isinstance(object_key, str)
                or not object_key.startswith(object_prefix)
                or not isinstance(size, int)
                or size < 0
                or not isinstance(digest, str)
                or not re.fullmatch(r"[0-9a-f]{64}", digest)
                or not isinstance(mode, int)
            ):
                raise RuntimeError("Runtime snapshot entry metadata is invalid")
            if relative in seen_paths:
                raise RuntimeError("Runtime snapshot contains duplicate paths")
            seen_paths.add(relative)
            destination = tenant_root / relative
            async with semaphore:
                await self._download_verified(object_key, destination, size, digest)
                destination.chmod(mode & 0o700 or 0o600)

        results = await asyncio.gather(
            *(restore(entry) for entry in manifest["files"]),
            return_exceptions=True,
        )
        for result in results:
            if isinstance(result, BaseException):
                raise result

    async def _restore_upload(self, user_id: UUID, row: Any) -> None:
        local_path = row["local_path"]
        object_key = row["object_key"]
        size = row["size_bytes"]
        digest = row["sha256"]
        if (
            not isinstance(local_path, str)
            or not isinstance(object_key, str)
            or not isinstance(size, int)
            or not isinstance(digest, str)
        ):
            raise RuntimeError("Stored upload metadata is incomplete")
        relative = tenant_relative_path(user_id, local_path, "uploads")
        if _has_symlink_component(self.settings.data_root.resolve(), relative):
            raise RuntimeError("Stored upload cache path contains a symbolic link")
        destination = self.settings.data_root / relative
        if destination.is_file():
            existing_digest, existing_size = await asyncio.to_thread(self._digest_file, destination)
            if existing_size == size and existing_digest == digest:
                return
        await self._download_verified(object_key, destination, size, digest)
        destination.chmod(0o600)

    async def _download_verified(
        self, object_key: str, destination: Path, size: int, digest: str
    ) -> None:
        assert self._object_store is not None
        destination.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
        temporary = destination.with_name(f".{destination.name}.{uuid4()}.part")
        try:
            await asyncio.to_thread(
                self._object_store.download_file,
                object_key,
                temporary,
            )
            actual_digest, actual_size = await asyncio.to_thread(self._digest_file, temporary)
            if actual_size != size or actual_digest != digest:
                raise RuntimeError("Restored GCS object failed integrity verification")
            temporary.replace(destination)
        finally:
            temporary.unlink(missing_ok=True)

    def _snapshot_pointer_key(self, user_id: UUID) -> str:
        return f"tenants/{user_id}/runtime-snapshots/current.json"

    @staticmethod
    def _snapshot_id(pointer: dict[str, Any]) -> str:
        snapshot_id = pointer.get("snapshot_id")
        if pointer.get("version") != RUNTIME_SNAPSHOT_VERSION or not isinstance(snapshot_id, str):
            raise RuntimeError("Runtime snapshot pointer is invalid")
        try:
            UUID(snapshot_id)
        except ValueError as error:
            raise RuntimeError("Runtime snapshot identifier is invalid") from error
        return snapshot_id

    async def _snapshot_json(self, object_key: str) -> dict[str, Any] | None:
        assert self._object_store is not None
        return await asyncio.to_thread(self._object_store.read_json, object_key)

    async def _put_snapshot_json(self, object_key: str, value: dict[str, Any]) -> None:
        assert self._object_store is not None
        await asyncio.to_thread(
            self._object_store.put_json,
            object_key,
            value,
        )

    async def _delete_snapshot_prefix(self, user_id: UUID, snapshot_id: str) -> None:
        assert self._object_store is not None
        prefix = f"tenants/{user_id}/runtime-snapshots/{snapshot_id}/"
        await self._delete_object_versions(prefix)

    async def _delete_noncurrent_pointer_versions(self, user_id: UUID) -> None:
        await self._delete_object_versions(
            self._snapshot_pointer_key(user_id),
            keep_latest_key=self._snapshot_pointer_key(user_id),
        )

    async def _delete_object_versions(
        self,
        prefix: str,
        *,
        keep_latest_key: str | None = None,
        exact_key: str | None = None,
    ) -> None:
        assert self._object_store is not None
        generations = await asyncio.to_thread(self._object_store.list_generations, prefix)
        obsolete = [
            item
            for item in generations
            if (exact_key is None or item.key == exact_key)
            and not (
                keep_latest_key is not None
                and item.key == keep_latest_key
                and item.is_latest
            )
        ]
        if obsolete:
            await asyncio.to_thread(self._object_store.delete_generations, obsolete)

    async def _upload_private(
        self, path: Path, object_key: str, content_type: str, digest: str
    ) -> None:
        assert self._object_store is not None
        await asyncio.to_thread(
            self._object_store.upload_file,
            path,
            object_key,
            content_type,
            digest,
        )

    @staticmethod
    def _digest_file(path: Path) -> tuple[str, int]:
        digest = hashlib.sha256()
        size = 0
        with path.open("rb") as source:
            while chunk := source.read(1024 * 1024):
                digest.update(chunk)
                size += len(chunk)
        return digest.hexdigest(), size
