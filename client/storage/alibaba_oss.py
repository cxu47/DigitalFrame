"""Read one-level photo albums from a confined Alibaba Cloud OSS prefix."""

from datetime import datetime, timezone
from dataclasses import dataclass
import logging

import alibabacloud_oss_v2 as oss
from alibabacloud_oss_v2.crc import Crc64
from dotenv import dotenv_values

from ..cache import supported_photo
from ..cancellation import check_cancelled
from ..config import (
    NETWORK_TIMEOUT,
    OSS_CREDENTIALS_FILE,
)


logger = logging.getLogger(__name__)
DOWNLOAD_CHUNK_SIZE = 1024 * 1024


def _required(name, values):
    value = values.get(name)
    if not isinstance(value, str) or not value.strip():
        raise ValueError(
            f"Missing required OSS setting: {name}. "
            f"Add it to {OSS_CREDENTIALS_FILE}."
        )
    return value.strip()


def _photos_prefix(values):
    value = str(values.get("OSS_PREFIX") or "photos").strip().strip("/")
    parts = value.split("/")
    if (not value or "\\" in value
            or any(not part or part in {".", ".."} for part in parts)):
        raise ValueError("OSS_PREFIX must name a folder inside the bucket.")
    return "/".join(parts) + "/"


@dataclass(frozen=True)
class OssStorage:
    client: object
    bucket: str
    prefix: str


def get_oss_storage():
    """Build one consistent OSS client/config snapshot for a sync pass."""
    values = dotenv_values(OSS_CREDENTIALS_FILE)
    region = _required("OSS_REGION", values)
    endpoint = str(values.get("OSS_ENDPOINT") or "").strip() or None
    if endpoint is not None and not endpoint.startswith("https://"):
        raise ValueError("OSS_ENDPOINT must use https://.")
    credentials = oss.credentials.StaticCredentialsProvider(
        _required("OSS_ACCESS_KEY_ID", values),
        _required("OSS_ACCESS_KEY_SECRET", values),
        values.get("OSS_SESSION_TOKEN") or None,
    )
    config = oss.config.load_default()
    config.credentials_provider = credentials
    config.region = region
    config.connect_timeout = NETWORK_TIMEOUT
    config.readwrite_timeout = NETWORK_TIMEOUT
    if endpoint is not None:
        config.endpoint = endpoint
    logger.debug("Building Alibaba OSS client for region %s", region)
    return OssStorage(
        client=oss.Client(config),
        bucket=_required("OSS_BUCKET_NAME", values),
        prefix=_photos_prefix(values),
    )


def _timestamp(value):
    if value is None:
        return None
    if isinstance(value, datetime):
        if value.tzinfo is None:
            value = value.replace(tzinfo=timezone.utc)
        return value.astimezone(timezone.utc).isoformat().replace("+00:00", "Z")
    return str(value)


def _pages(client, request, stop_event):
    paginator = client.list_objects_v2_paginator()
    for page in paginator.iter_page(request):
        check_cancelled(stop_event)
        yield page


def _album_name(album_prefix, photos_prefix):
    if not album_prefix.startswith(photos_prefix) or not album_prefix.endswith("/"):
        raise RuntimeError("OSS returned an album outside the configured photos prefix")
    relative = album_prefix[len(photos_prefix):-1]
    if not relative or "/" in relative:
        raise RuntimeError("OSS returned an invalid immediate album prefix")
    return relative


def _object_name(object_key, album_prefix):
    if not isinstance(object_key, str) or not object_key.startswith(album_prefix):
        raise RuntimeError("OSS returned an object outside its requested album prefix")
    relative = object_key[len(album_prefix):]
    if not relative or "/" in relative:
        return None
    return relative


def _object_metadata(item, name):
    modified = _timestamp(item.last_modified)
    metadata = {
        "id": item.key,
        "name": name,
        "size": item.size,
        # ListObjectsV2 does not expose creation time. Last-modified is the
        # stable timestamp available for offline ordering and month buckets.
        "createdTime": modified,
        "modifiedTime": modified,
    }
    if item.etag:
        metadata["etag"] = item.etag.strip('"')
    return metadata


def list_albums(*, storage=None, stop_event=None):
    """Return immediate albums and photos below the configured OSS prefix."""
    storage = storage if storage is not None else get_oss_storage()
    client = storage.client
    prefixes = set()
    root_request = oss.ListObjectsV2Request(
        bucket=storage.bucket,
        prefix=storage.prefix,
        delimiter="/",
    )
    for page in _pages(client, root_request, stop_event):
        for item in page.common_prefixes or ():
            _album_name(item.prefix, storage.prefix)
            prefixes.add(item.prefix)

    albums = []
    for album_prefix in sorted(prefixes):
        check_cancelled(stop_event)
        album = {
            "id": album_prefix,
            "name": _album_name(album_prefix, storage.prefix),
            "photos": [],
        }
        request = oss.ListObjectsV2Request(
            bucket=storage.bucket,
            prefix=album_prefix,
            delimiter="/",
        )
        for page in _pages(client, request, stop_event):
            for item in page.contents or ():
                check_cancelled(stop_event)
                if item.key == album_prefix:
                    modified = _timestamp(item.last_modified)
                    album.update(createdTime=modified, modifiedTime=modified)
                    continue
                name = _object_name(item.key, album_prefix)
                if name is not None and supported_photo(name):
                    album["photos"].append(_object_metadata(item, name))
        albums.append(album)
    return albums


def _confined_photo_key(object_key, photos_prefix):
    if not isinstance(object_key, str) or not object_key.startswith(photos_prefix):
        raise ValueError("OSS object key is outside the configured photos prefix")
    parts = object_key[len(photos_prefix):].split("/")
    if len(parts) != 2 or any(not part for part in parts):
        raise ValueError("OSS photo key must be directly inside an album")
    return object_key


def download_photo(object_key, destination, *, storage=None, stop_event=None):
    """Stream one confined photo object into the sync staging path."""
    storage = storage if storage is not None else get_oss_storage()
    object_key = _confined_photo_key(object_key, storage.prefix)
    check_cancelled(stop_event)
    result = storage.client.get_object(oss.GetObjectRequest(
        bucket=storage.bucket, key=object_key))
    logger.debug("Starting Alibaba OSS object download")
    checksum = Crc64(0)
    with result.body as body, open(destination, "wb") as output:
        for chunk in body.iter_bytes(block_size=DOWNLOAD_CHUNK_SIZE):
            check_cancelled(stop_event)
            output.write(chunk)
            checksum.update(chunk)
    server_checksum = getattr(result, "hash_crc64", None)
    if server_checksum is not None and checksum.sum64() != int(server_checksum):
        raise oss.exceptions.InconsistentError(
            client_crc=str(checksum.sum64()), server_crc=str(server_checksum))
    logger.debug("Alibaba OSS object download completed")
