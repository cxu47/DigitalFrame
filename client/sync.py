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

from .config import CACHE_DIR, GOOGLE_DRIVE_FOLDER_ID
from .logging_config import configure_logging
from .storage.google_drive import get_drive_service, list_albums, download_photo
from .cache import cached_folders, cached_photos, supported_photo
from .cancellation import Cancelled, check_cancelled
from .status import is_network_error

logger = logging.getLogger(__name__)
MANIFEST = ".photos.json"


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
        names = _names(supported)
        for photo in supported:
            photos[photo["id"]] = {
                "path": f'{folders[album["id"]]}/{names[photo["id"]]}',
                "md5": photo.get("md5Checksum"),
                "size": int(photo["size"]) if "size" in photo else None,
                "modified": photo.get("modifiedTime"),
            }
    return {"folders": folders, "photos": photos}


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
    local = cached_photos(CACHE_DIR)
    hashes = {}
    for path in local:
        check_cancelled(stop_event)
        try:
            hashes[path] = file_hash(path, stop_event)
        except OSError:
            logger.warning("Unable to read cached photo %s; will retrieve it from Drive", path.name)
    with TemporaryDirectory(prefix=".sync-", dir=CACHE_DIR) as staging:
        reusable = {}
        wanted_hashes = {entry["md5"] for entry in catalog["photos"].values() if entry["md5"]}
        # Temporary hard links preserve verified content through name swaps.
        # They do not duplicate image bytes or serve as recovery backups.
        for path, digest in hashes.items():
            if digest in wanted_hashes and digest not in reusable:
                target = Path(staging) / digest
                os.link(path, target)
                reusable[digest] = target
        for folder in catalog["folders"].values():
            _cache_path(f"{folder}/placeholder").parent.mkdir(exist_ok=True)
        for file_id, entry in catalog["photos"].items():
            check_cancelled(stop_event)
            destination = _cache_path(entry["path"])
            expected = entry["md5"]
            if expected and hashes.get(destination) == expected:
                continue
            temporary = Path(staging) / "download.part"
            try:
                temporary.unlink(missing_ok=True)
                if expected in reusable:
                    os.link(reusable[expected], temporary)
                else:
                    logger.info("Downloading %s", entry["path"])
                    download_photo(file_id, temporary, service=service, stop_event=stop_event)
                    result.downloaded += 1
                check_cancelled(stop_event)
                if expected and file_hash(temporary, stop_event) != expected:
                    raise ValueError("Downloaded bytes do not match the Google Drive checksum; will retry.")
                if entry["size"] is not None and temporary.stat().st_size != entry["size"]:
                    raise ValueError("Downloaded size does not match Google Drive; will retry.")
                temporary.replace(destination)
                if new_photos is not None:
                    new_photos.put(destination)
            except Cancelled:
                raise
            except Exception as exc:
                result.failed += 1
                result.network_error = result.network_error or is_network_error(exc)
                result.error = f"{entry['path']}: {type(exc).__name__}: {exc}"
                logger.exception("Unable to refresh %s; keeping existing cached files", entry["path"])
            finally:
                temporary.unlink(missing_ok=True)

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
        manifest = {"schema": 2, **catalog,
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
