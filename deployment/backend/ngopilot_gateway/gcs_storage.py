"""Google Cloud Storage adapter for private NGOPilot objects."""

from __future__ import annotations

import json
from dataclasses import dataclass
from datetime import timedelta
from pathlib import Path
from typing import Any

from google.api_core.exceptions import NotFound
from google.cloud import storage
from google.oauth2 import service_account

from .config import Settings

GCS_OPERATION_TIMEOUT_SECONDS = 120


@dataclass(frozen=True, slots=True)
class ObjectGeneration:
    key: str
    generation: int
    is_latest: bool


class GcsObjectStore:
    def __init__(self, settings: Settings) -> None:
        credentials = service_account.Credentials.from_service_account_info(
            settings.gcp_service_account_info
        )
        self.bucket_name = settings.gcs_bucket
        self._client = storage.Client(
            project=settings.gcp_project_id,
            credentials=credentials,
        )
        self._bucket = self._client.bucket(self.bucket_name)

    def health_check(self) -> None:
        blobs = self._client.list_blobs(
            self.bucket_name,
            max_results=1,
            page_size=1,
            timeout=10,
        )
        next(iter(blobs), None)

    def upload_file(
        self,
        path: Path,
        object_key: str,
        content_type: str,
        digest: str,
    ) -> None:
        blob = self._bucket.blob(object_key)
        blob.metadata = {"sha256": digest}
        blob.upload_from_filename(
            str(path),
            content_type=content_type,
            checksum="auto",
            timeout=GCS_OPERATION_TIMEOUT_SECONDS,
        )

    def download_file(self, object_key: str, destination: Path) -> None:
        self._bucket.blob(object_key).download_to_filename(
            str(destination),
            checksum="auto",
            timeout=GCS_OPERATION_TIMEOUT_SECONDS,
        )

    def object_matches(self, object_key: str, size: int, digest: str) -> bool:
        blob = self._bucket.blob(object_key)
        try:
            blob.reload(timeout=GCS_OPERATION_TIMEOUT_SECONDS)
        except NotFound:
            return False
        metadata = {str(key).lower(): str(value) for key, value in (blob.metadata or {}).items()}
        return blob.size == size and metadata.get("sha256") == digest

    def read_json(self, object_key: str) -> dict[str, Any] | None:
        blob = self._bucket.blob(object_key)
        try:
            body = blob.download_as_bytes(
                checksum="auto",
                timeout=GCS_OPERATION_TIMEOUT_SECONDS,
            )
        except NotFound:
            return None
        value = json.loads(body)
        if not isinstance(value, dict):
            raise RuntimeError("GCS snapshot metadata is invalid")
        return value

    def put_json(self, object_key: str, value: dict[str, Any]) -> None:
        body = json.dumps(value, separators=(",", ":"), sort_keys=True).encode("utf-8")
        self._bucket.blob(object_key).upload_from_string(
            body,
            content_type="application/json",
            checksum="auto",
            timeout=GCS_OPERATION_TIMEOUT_SECONDS,
        )

    def sign_download(
        self,
        object_key: str,
        filename: str,
        content_type: str,
        expires_in: int,
    ) -> str:
        url = self._bucket.blob(object_key).generate_signed_url(
            version="v4",
            expiration=timedelta(seconds=expires_in),
            method="GET",
            response_disposition=f'attachment; filename="{filename}"',
            response_type=content_type,
        )
        if not url:
            raise RuntimeError("GCS did not return a signed download URL")
        return url

    def list_generations(self, prefix: str) -> list[ObjectGeneration]:
        blobs = list(
            self._client.list_blobs(
                self.bucket_name,
                prefix=prefix,
                versions=True,
                timeout=GCS_OPERATION_TIMEOUT_SECONDS,
            )
        )
        latest_by_key: dict[str, int] = {}
        for blob in blobs:
            if blob.generation is None:
                raise RuntimeError("GCS returned an object without a generation")
            generation = int(blob.generation)
            latest_by_key[blob.name] = max(generation, latest_by_key.get(blob.name, 0))
        return [
            ObjectGeneration(
                key=blob.name,
                generation=int(blob.generation),
                is_latest=int(blob.generation) == latest_by_key[blob.name],
            )
            for blob in blobs
        ]

    def delete_generations(self, generations: list[ObjectGeneration]) -> None:
        for item in generations:
            try:
                self._bucket.blob(item.key, generation=item.generation).delete(
                    if_generation_match=item.generation,
                    timeout=GCS_OPERATION_TIMEOUT_SECONDS,
                )
            except NotFound:
                continue
