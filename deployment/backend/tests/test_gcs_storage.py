from __future__ import annotations

from types import SimpleNamespace

from google.api_core.exceptions import NotFound

from ngopilot_gateway.gcs_storage import GcsObjectStore, ObjectGeneration


class Bucket:
    def __init__(self, blob) -> None:
        self._blob = blob
        self.requests: list[tuple[str, int | None]] = []

    def blob(self, name: str, generation: int | None = None):
        self.requests.append((name, generation))
        return self._blob


def object_store(bucket, client=None) -> GcsObjectStore:
    store = object.__new__(GcsObjectStore)
    store.bucket_name = "ngopilot-test"
    store._bucket = bucket
    store._client = client
    return store


def test_upload_sets_integrity_metadata_and_uses_sdk_checksum(tmp_path) -> None:
    path = tmp_path / "report.xlsx"
    path.write_bytes(b"workbook")

    class Blob:
        metadata = None

        def upload_from_filename(self, filename, **kwargs):
            self.filename = filename
            self.kwargs = kwargs

    blob = Blob()
    store = object_store(Bucket(blob))

    store.upload_file(path, "tenants/user/artifacts/id", "application/xlsx", "a" * 64)

    assert blob.filename == str(path)
    assert blob.metadata == {"sha256": "a" * 64}
    assert blob.kwargs["content_type"] == "application/xlsx"
    assert blob.kwargs["checksum"] == "auto"


def test_health_check_lists_only_one_object_from_configured_bucket() -> None:
    class Client:
        def list_blobs(self, bucket_name, **kwargs):
            self.bucket_name = bucket_name
            self.kwargs = kwargs
            return iter(())

    client = Client()

    object_store(Bucket(None), client).health_check()

    assert client.bucket_name == "ngopilot-test"
    assert client.kwargs["max_results"] == 1
    assert client.kwargs["page_size"] == 1


def test_signed_download_uses_v4_and_attachment_response_headers() -> None:
    class Blob:
        def generate_signed_url(self, **kwargs):
            self.kwargs = kwargs
            return "https://storage.googleapis.com/signed"

    blob = Blob()
    store = object_store(Bucket(blob))

    url = store.sign_download(
        "tenants/user/artifacts/id",
        "report.xlsx",
        "application/xlsx",
        300,
    )

    assert url == "https://storage.googleapis.com/signed"
    assert blob.kwargs["version"] == "v4"
    assert blob.kwargs["response_disposition"] == 'attachment; filename="report.xlsx"'
    assert blob.kwargs["response_type"] == "application/xlsx"
    assert blob.kwargs["expiration"].total_seconds() == 300


def test_missing_json_object_returns_none() -> None:
    class Blob:
        def download_as_bytes(self, **kwargs):
            raise NotFound("missing")

    assert object_store(Bucket(Blob())).read_json("missing.json") is None


def test_object_match_uses_size_and_sha256_metadata() -> None:
    class Blob:
        size = 8
        metadata = {"sha256": "a" * 64}

        def reload(self, **kwargs):
            self.kwargs = kwargs

    assert object_store(Bucket(Blob())).object_matches("object", 8, "a" * 64) is True


def test_generation_listing_marks_highest_generation_as_latest() -> None:
    blobs = [
        SimpleNamespace(name="tenants/user/current.json", generation=100),
        SimpleNamespace(name="tenants/user/current.json", generation=200),
        SimpleNamespace(name="tenants/user/old.json", generation=150),
    ]

    class Client:
        def list_blobs(self, bucket_name, **kwargs):
            self.bucket_name = bucket_name
            self.kwargs = kwargs
            return blobs

    client = Client()
    generations = object_store(Bucket(None), client).list_generations("tenants/user/")

    assert generations == [
        ObjectGeneration("tenants/user/current.json", 100, False),
        ObjectGeneration("tenants/user/current.json", 200, True),
        ObjectGeneration("tenants/user/old.json", 150, True),
    ]
    assert client.kwargs["versions"] is True
    assert client.kwargs["prefix"] == "tenants/user/"


def test_generation_deletion_uses_generation_precondition() -> None:
    class Blob:
        def delete(self, **kwargs):
            self.kwargs = kwargs

    blob = Blob()
    bucket = Bucket(blob)

    object_store(bucket).delete_generations([ObjectGeneration("object", 123, True)])

    assert bucket.requests == [("object", 123)]
    assert blob.kwargs["if_generation_match"] == 123
