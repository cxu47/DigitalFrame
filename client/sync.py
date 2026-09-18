"""Reconcile a disposable photo cache against fresh, complete Drive metadata."""

from contextlib import contextmanager
from dataclasses import dataclass
import fcntl
import hashlib
import json
import logging
import os
from pathlib import Path
import shutil
from tempfile import TemporaryDirectory

from PIL import Image, ImageOps, UnidentifiedImageError
from pillow_heif import register_heif_opener

from .config import (CACHE_DIR, CACHE_MAX_HEIGHT, CACHE_MAX_WIDTH,
                     GOOGLE_DRIVE_FOLDER_ID, IPHONE_JPEG_QUALITY, OTHER_IMAGE_QUALITY)
from .logging_config import configure_logging
from .storage.google_drive import get_drive_service, list_albums, download_photo
from .cache import (MANIFEST, PhotoArrival, cached_folders, cached_photos,
                    iphone_photo, newest_first, photo_month, supported_photo)
from .cancellation import Cancelled, check_cancelled
from .status import is_network_error

logger = logging.getLogger(__name__)
register_heif_opener()
CACHE_PROCESSING_PROFILE = (
    f"fit-{CACHE_MAX_WIDTH}x{CACHE_MAX_HEIGHT}-other{OTHER_IMAGE_QUALITY}"
    f"-iphone{IPHONE_JPEG_QUALITY}-v3")


@dataclass
class SyncResult:
    success: bool = False
    downloaded: int = 0
    failed: int = 0
    cancelled: bool = False
    error: str = ""
    network_error: bool = False


@contextmanager
def cache_lock():
    CACHE_DIR.mkdir(parents=True, exist_ok=True)
    # Keep this file in place: unlinking it could let two processes lock
    # different inodes while both believe they own this cache.
    with (CACHE_DIR / ".sync.lock").open("a") as lock:
        try:
            fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError:
            raise RuntimeError("Another sync process is already using this cache.") from None
        try:
            yield
        finally:
            fcntl.flock(lock, fcntl.LOCK_UN)


def _names(items):
    """Preserve normal names, escaping path separators and disambiguating Drive duplicates."""
    result = {}
    used = set()
    for item in sorted(items, key=lambda item: item["id"]):
        name = item["name"].replace("/", "_").replace("\\", "_").replace("\x00", "_")
        name = name.lstrip(".") or "untitled"
        # Leave room for suffixes and the download's .part extension.
        while len(name.encode("utf-8")) > 180:
            stem, suffix = Path(name).stem, Path(name).suffix
            name = stem[:-1] + suffix if stem else name[:-1]
        original = Path(name)
        index = 0
        while name.casefold() in used:
            index += 1
            tag = hashlib.sha256(item["id"].encode()).hexdigest()[:12]
            name = f"{original.stem} ({tag}-{index}){original.suffix}"
        used.add(name.casefold())
        result[item["id"]] = name
    return result


def _catalog(albums):
    folders = _names(albums)
    photos = {}
    for album in albums:
        supported = [photo for photo in album["photos"] if supported_photo(photo["name"])]
        playback_items = [
            {**photo, "name": f"{Path(photo['name']).stem}.jpg"}
            if iphone_photo(photo["name"]) else photo
            for photo in supported
        ]
        names = _names(playback_items)
        for photo in supported:
            photos[photo["id"]] = {
                "path": f'{folders[album["id"]]}/{names[photo["id"]]}',
                "source_name": photo["name"],
                "converted": iphone_photo(photo["name"]),
                "processing": CACHE_PROCESSING_PROFILE,
                "md5": photo.get("md5Checksum"),
                "size": int(photo["size"]) if "size" in photo else None,
                "modified": photo.get("modifiedTime"),
                "created": photo.get("createdTime"),
                "month": photo_month(photo.get("createdTime")),
            }
    folder_metadata = {folders[album["id"]]: {
        "created": album.get("createdTime"), "modified": album.get("modifiedTime")
    } for album in albums}
    return {"folders": folders, "folder_metadata": folder_metadata, "photos": photos}


def _cache_path(relative):
    path = Path(relative)
    if path.is_absolute() or len(path.parts) != 2 or any(part.startswith(".") for part in path.parts):
        raise ValueError("Invalid cached photo path")
    destination = CACHE_DIR / path
    if destination.is_symlink() or destination.parent.is_symlink():
        raise ValueError("Symlinks are not supported in the photo cache")
    return destination


def file_hash(path, stop_event=None):
    digest = hashlib.md5(usedforsecurity=False)
    with path.open("rb") as source:
        while chunk := source.read(1024 * 1024):
            check_cancelled(stop_event)
            digest.update(chunk)
    return digest.hexdigest()


def sha256_hash(path, stop_event=None):
    digest = hashlib.sha256()
    with path.open("rb") as source:
        while chunk := source.read(1024 * 1024):
            check_cancelled(stop_event)
            digest.update(chunk)
    return digest.hexdigest()


def _previous_catalog():
    try:
        value = json.loads((CACHE_DIR / MANIFEST).read_text(encoding="utf-8"))
    except (OSError, ValueError, UnicodeError):
        return {}
    return value if isinstance(value, dict) else {}


def _same_source(previous, current):
    if not previous:
        return False
    if current.get("md5"):
        return previous.get("md5") == current["md5"]
    # Drive normally supplies MD5 for binary HEIC/HEIF files. If it does not,
    # stable size and modification metadata are the best available identity.
    return (current.get("size") is not None and current.get("modified") is not None
            and previous.get("size") == current["size"]
            and previous.get("modified") == current["modified"])


def _prepare_cached_photo(source, destination, entry):
    """Create a bounded derivative when needed; return False for a direct copy."""
    try:
        image = Image.open(source)
    except UnidentifiedImageError:
        # Preserve the existing download behavior. Playback will reject an
        # invalid image, while the next sync can repair it if Drive changes.
        return False
    with image:
        oriented = ImageOps.exif_transpose(image)
        try:
            needs_derivative = (entry["converted"] or oriented.width > CACHE_MAX_WIDTH
                                or oriented.height > CACHE_MAX_HEIGHT)
            if not needs_derivative:
                return False
            oriented.thumbnail(
                (CACHE_MAX_WIDTH, CACHE_MAX_HEIGHT), Image.Resampling.LANCZOS)
            suffix = Path(entry["path"]).suffix.lower()
            if suffix in {".jpg", ".jpeg"}:
                output = oriented if oriented.mode == "RGB" else oriented.convert("RGB")
                try:
                    quality = IPHONE_JPEG_QUALITY if entry["converted"] else OTHER_IMAGE_QUALITY
                    output.save(
                        destination, format="JPEG", quality=quality,
                        optimize=True, progressive=True, subsampling="4:2:0",
                    )
                finally:
                    if output is not oriented:
                        output.close()
            elif suffix == ".png":
                oriented.save(destination, format="PNG", optimize=True)
            elif suffix == ".webp":
                oriented.save(
                    destination, format="WEBP", quality=OTHER_IMAGE_QUALITY, method=4)
            else:
                raise ValueError("Unsupported cached image format")
            return True
        finally:
            if oriented is not image:
                oriented.close()


def sync_photos(new_photos=None, *, stop_event=None, status=None):
    result = SyncResult()
    service = None
    try:
        with cache_lock():
            check_cancelled(stop_event)
            # One transport belongs to this sync thread for the entire pass.
            service = get_drive_service()
            catalog = _catalog(list_albums(GOOGLE_DRIVE_FOLDER_ID, service=service, stop_event=stop_event))
            check_cancelled(stop_event)
            _reconcile(catalog, service, result, new_photos, stop_event)
        result.success = not result.failed
        if status is not None:
            if result.success:
                status.clear("Sync")
            else:
                status.report("Sync", result.error, network=result.network_error)
    except Cancelled:
        result.cancelled = True
    except Exception as exc:
        result.error = f"{type(exc).__name__}: {exc}"
        result.network_error = is_network_error(exc)
        logger.exception("Photo sync failed; cached playback will continue")
        if status is not None:
            status.report("Sync", result.error, network=result.network_error)
    finally:
        if service is not None:
            try:
                service.close()
            except Exception:
                logger.warning("Could not close the Drive transport", exc_info=True)
    return result


def _reconcile(catalog, service, result, new_photos, stop_event):
    # Remove staging left by a killed process, after obtaining the process lock
    # and a complete Drive listing. These are temporary links, never backups.
    for abandoned in CACHE_DIR.glob(".sync-*"):
        check_cancelled(stop_event)
        if abandoned.is_dir() and not abandoned.is_symlink():
            shutil.rmtree(abandoned)
    # Hash actual bytes every pass. An old/corrupt manifest is never evidence
    # that a local photo is correct; only current Drive metadata is authoritative.
    previous = _previous_catalog()
    previous_photos = previous.get("photos", {}) if isinstance(previous.get("photos"), dict) else {}
    local = cached_photos(CACHE_DIR, source_formats=True)
    hashes = {}
    for path in local:
        check_cancelled(stop_event)
        try:
            hashes[path] = file_hash(path, stop_event)
        except OSError:
            logger.warning("Unable to read cached photo %s; will retrieve it from Drive", path.name)
    with TemporaryDirectory(prefix=".sync-", dir=CACHE_DIR) as staging:
        reusable = {}
        processed_reusable = {}
        wanted_hashes = {entry["md5"] for entry in catalog["photos"].values()
                         if entry["md5"] and not entry["converted"]}
        # Temporary hard links preserve verified content through name swaps.
        # They do not duplicate image bytes or serve as recovery backups.
        for path, digest in hashes.items():
            if digest in wanted_hashes and digest not in reusable:
                target = Path(staging) / digest
                os.link(path, target)
                reusable[digest] = target
        # A resized or converted cache file cannot match its source Drive MD5.
        # Verify every processed file against its own SHA-256, source identity,
        # and the current processing profile before reusing it.
        for file_id, entry in catalog["photos"].items():
            old = previous_photos.get(file_id)
            if (not _same_source(old, entry)
                    or old.get("processing") != entry["processing"]):
                continue
            try:
                old_path = _cache_path(old["path"])
                expected_sha = old.get("cache_sha256")
                if expected_sha and old_path in hashes and sha256_hash(old_path, stop_event) == expected_sha:
                    target = Path(staging) / f"converted-{file_id}"
                    os.link(old_path, target)
                    processed_reusable[file_id] = (target, expected_sha)
            except (KeyError, OSError, ValueError):
                continue
        for folder in catalog["folders"].values():
            _cache_path(f"{folder}/placeholder").parent.mkdir(exist_ok=True)
        # Across all albums, publish newer uploads first so the arrival queue
        # follows the same default order while the first sync is still running.
        for file_id, entry in sorted(catalog["photos"].items(),
                                     key=lambda item: newest_first(item[1].get("created"))):
            check_cancelled(stop_event)
            destination = _cache_path(entry["path"])
            expected = entry["md5"]
            if file_id in processed_reusable and destination.exists():
                reusable_path, expected_sha = processed_reusable[file_id]
                if sha256_hash(destination, stop_event) == expected_sha:
                    entry["cache_sha256"] = expected_sha
                    continue
            temporary = Path(staging) / "download.part"
            publication = Path(staging) / "publication.part"
            try:
                temporary.unlink(missing_ok=True)
                publication.unlink(missing_ok=True)
                if file_id in processed_reusable:
                    reusable_path, expected_sha = processed_reusable[file_id]
                    os.link(reusable_path, publication)
                    entry["cache_sha256"] = expected_sha
                elif expected in reusable:
                    os.link(reusable[expected], temporary)
                else:
                    logger.info("Downloading %s", entry["source_name"])
                    download_photo(file_id, temporary, service=service, stop_event=stop_event)
                    result.downloaded += 1
                check_cancelled(stop_event)
                if not publication.exists():
                    if expected and file_hash(temporary, stop_event) != expected:
                        raise ValueError("Downloaded bytes do not match the Google Drive checksum; will retry.")
                    if entry["size"] is not None and temporary.stat().st_size != entry["size"]:
                        raise ValueError("Downloaded size does not match Google Drive; will retry.")
                    if _prepare_cached_photo(temporary, publication, entry):
                        published = publication
                    else:
                        published = temporary
                    entry["cache_sha256"] = sha256_hash(published, stop_event)
                else:
                    published = publication
                published.replace(destination)
                if new_photos is not None:
                    new_photos.put(PhotoArrival(destination, entry.get("month")))
            except Cancelled:
                raise
            except Exception as exc:
                result.failed += 1
                result.network_error = result.network_error or is_network_error(exc)
                result.error = f"{entry['path']}: {type(exc).__name__}: {exc}"
                logger.exception("Unable to refresh %s; keeping existing cached files", entry["path"])
            finally:
                temporary.unlink(missing_ok=True)
                publication.unlink(missing_ok=True)

    check_cancelled(stop_event)
    # Only a fully successful pass removes obsolete album photos. This also
    # rebuilds correctly when the old manifest was absent or corrupted.
    if not result.failed:
        wanted_paths = {entry["path"] for entry in catalog["photos"].values()}
        for path in local:
            check_cancelled(stop_event)
            if str(path.relative_to(CACHE_DIR)) not in wanted_paths:
                path.unlink(missing_ok=True)
        for folder in cached_folders(CACHE_DIR):
            if folder not in catalog["folders"].values():
                try:
                    (CACHE_DIR / folder).rmdir()
                except OSError:
                    pass  # Unrelated non-photo files are not removed.
        manifest = {"schema": 6, **catalog,
                    "hash": hashlib.sha256(json.dumps(catalog, sort_keys=True).encode()).hexdigest()}
        encoded = json.dumps(manifest, sort_keys=True)
        try:
            unchanged = (CACHE_DIR / MANIFEST).read_text(encoding="utf-8") == encoded
        except (OSError, UnicodeError):
            unchanged = False
        if not unchanged:
            temporary = CACHE_DIR / (MANIFEST + ".part")
            temporary.write_text(encoded, encoding="utf-8")
            temporary.replace(CACHE_DIR / MANIFEST)
    log = logger.info if result.downloaded or result.failed else logger.debug
    log("Photo sync completed: %d remote, %d downloaded, %d failed",
        len(catalog["photos"]), result.downloaded, result.failed)


if __name__ == "__main__":
    configure_logging()
    raise SystemExit(0 if sync_photos().success else 1)
