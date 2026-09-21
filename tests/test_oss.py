"""Exercise Alibaba OSS configuration and I/O at the SDK boundary."""

from datetime import datetime, timezone
from types import SimpleNamespace
from unittest.mock import Mock

from alibabacloud_oss_v2.crc import Crc64
import pytest


def _object(key, *, size=3, etag='"etag"', modified=None):
    return SimpleNamespace(
        key=key,
        size=size,
        etag=etag,
        last_modified=modified or datetime(2026, 9, 12, tzinfo=timezone.utc),
    )


def _prefix(value):
    return SimpleNamespace(prefix=value)


def test_client_loads_secret_file_and_applies_region_endpoint_and_timeouts(app, monkeypatch):
    credentials_file = app.oss.OSS_CREDENTIALS_FILE
    credentials_file.write_text(
        "OSS_ACCESS_KEY_ID=local-id\n"
        "OSS_ACCESS_KEY_SECRET=local-secret\n"
        "OSS_SESSION_TOKEN=local-token\n"
        "OSS_BUCKET_NAME=local-bucket\n"
        "OSS_REGION=cn-local\n"
        "OSS_ENDPOINT=https://oss.example.invalid\n"
        "OSS_PREFIX=photos/\n",
        encoding="utf-8",
    )
    config = SimpleNamespace()
    client = Mock()
    monkeypatch.setattr(app.oss.oss.config, "load_default", Mock(return_value=config))
    monkeypatch.setattr(app.oss.oss, "Client", Mock(return_value=client))
    storage = app.oss.get_oss_storage()

    credentials = config.credentials_provider.get_credentials()
    assert credentials.access_key_id == "local-id"
    assert credentials.access_key_secret == "local-secret"
    assert credentials.security_token == "local-token"
    assert config.region == "cn-local"
    assert config.endpoint == "https://oss.example.invalid"
    assert config.connect_timeout == app.oss.NETWORK_TIMEOUT
    assert config.readwrite_timeout == app.oss.NETWORK_TIMEOUT
    assert storage.client is client
    assert storage.bucket == "local-bucket"
    assert storage.prefix == "photos/"


def test_missing_credentials_are_reported_without_exposing_other_values(app):
    app.oss.OSS_CREDENTIALS_FILE.write_text(
        "OSS_ACCESS_KEY_ID=do-not-print-this\n"
        "OSS_BUCKET_NAME=test-bucket\n"
        "OSS_REGION=cn-test\n"
        "OSS_PREFIX=photos/\n",
        encoding="utf-8",
    )
    with pytest.raises(ValueError, match="OSS_ACCESS_KEY_SECRET") as error:
        app.oss.get_oss_storage()
    assert "do-not-print-this" not in str(error.value)


def test_album_listing_paginates_and_only_reads_immediate_photos_prefix(app):
    requests = []
    pages = {
        "photos/": [
            SimpleNamespace(contents=[], common_prefixes=[_prefix("photos/kids/")]),
            SimpleNamespace(contents=[], common_prefixes=[
                _prefix("photos/empty/"), _prefix("photos/summer/")]),
        ],
        "photos/empty/": [SimpleNamespace(
            contents=[_object("photos/empty/", size=0)], common_prefixes=[])],
        "photos/kids/": [SimpleNamespace(contents=[
            _object("photos/kids/"),
            _object("photos/kids/one.jpg", etag='"one-etag"'),
            _object("photos/kids/readme.txt"),
            _object("photos/kids/nested/deep.jpg"),
        ], common_prefixes=[_prefix("photos/kids/nested/")])],
        "photos/summer/": [SimpleNamespace(
            contents=[_object("photos/summer/two.HEIC", size=8)], common_prefixes=[])],
    }

    class Paginator:
        def iter_page(self, request):
            requests.append(request)
            return iter(pages[request.prefix])

    client = Mock()
    client.list_objects_v2_paginator.side_effect = Paginator
    storage = app.oss.OssStorage(client, "test-bucket", "photos/")

    albums = app.oss.list_albums(storage=storage)

    assert [album["name"] for album in albums] == ["empty", "kids", "summer"]
    assert albums[0]["photos"] == []
    assert albums[0]["modifiedTime"] == "2026-09-12T00:00:00Z"
    assert albums[1]["photos"] == [{
        "id": "photos/kids/one.jpg",
        "name": "one.jpg",
        "size": 3,
        "createdTime": "2026-09-12T00:00:00Z",
        "modifiedTime": "2026-09-12T00:00:00Z",
        "etag": "one-etag",
    }]
    assert albums[2]["photos"][0]["name"] == "two.HEIC"
    assert [request.prefix for request in requests] == [
        "photos/", "photos/empty/", "photos/kids/", "photos/summer/",
    ]
    assert all(request.bucket == "test-bucket" for request in requests)
    assert all(request.delimiter == "/" for request in requests)


def test_listing_rejects_an_album_outside_the_configured_prefix(app):
    page = SimpleNamespace(contents=[], common_prefixes=[_prefix("private/")])
    paginator = Mock()
    paginator.iter_page.return_value = iter([page])
    client = Mock()
    client.list_objects_v2_paginator.return_value = paginator
    storage = app.oss.OssStorage(client, "test-bucket", "photos/")

    with pytest.raises(RuntimeError, match="outside"):
        app.oss.list_albums(storage=storage)


def test_download_streams_chunks_and_rejects_keys_outside_direct_albums(app, tmp_path):
    class Body:
        def __init__(self):
            self.closed = False

        def __enter__(self):
            return self

        def __exit__(self, *args):
            self.closed = True

        def iter_bytes(self, *, block_size):
            assert block_size == app.oss.DOWNLOAD_CHUNK_SIZE
            yield b"abc"
            yield b"def"

    body = Body()
    client = Mock()
    checksum = Crc64(0)
    checksum.update(b"abcdef")
    client.get_object.return_value = SimpleNamespace(
        body=body, hash_crc64=str(checksum.sum64()))
    storage = app.oss.OssStorage(client, "test-bucket", "photos/")
    destination = tmp_path / "photo.jpg.part"

    app.oss.download_photo("photos/kids/photo.jpg", destination, storage=storage)

    assert destination.read_bytes() == b"abcdef"
    request = client.get_object.call_args.args[0]
    assert request.bucket == "test-bucket"
    assert request.key == "photos/kids/photo.jpg"
    assert body.closed

    for key in ("private/photo.jpg", "photos/loose.jpg", "photos/kids/nested/photo.jpg"):
        with pytest.raises(ValueError):
            app.oss.download_photo(key, destination, storage=storage)
    assert client.get_object.call_count == 1


def test_download_rejects_an_oss_crc64_mismatch(app, tmp_path):
    body = Mock()
    body.__enter__ = Mock(return_value=body)
    body.__exit__ = Mock(return_value=None)
    body.iter_bytes.return_value = iter([b"damaged"])
    client = Mock()
    client.get_object.return_value = SimpleNamespace(body=body, hash_crc64="1")
    storage = app.oss.OssStorage(client, "test-bucket", "photos/")

    with pytest.raises(app.oss.oss.exceptions.InconsistentError):
        app.oss.download_photo(
            "photos/kids/photo.jpg", tmp_path / "photo.part", storage=storage)
