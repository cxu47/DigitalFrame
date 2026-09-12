import hashlib
import json
import logging
from pathlib import Path
import shutil
from tempfile import TemporaryDirectory
from threading import Lock

from .config import CACHE_DIR, GOOGLE_DRIVE_FOLDER_ID
from .logging_config import configure_logging
from .storage.google_drive import list_albums, download_photo


logger = logging.getLogger(__name__)
_sync_lock = Lock()
MANIFEST = ".photos.json"


def _names(items):
    """Preserve normal names, escaping path separators and disambiguating Drive duplicates."""
    result = {}
    used = set()
    for item in sorted(items, key=lambda item: item["id"]):
        name = item["name"].replace("/", "_").replace("\\", "_").replace("\x00", "_")
        name = name.lstrip(".") or "untitled"
        # Leave room for suffixes and the download's .part extension.
        while len(name.encode("utf-8")) > 180:
            name = name[:-1]
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
        names = _names(album["photos"])
        for photo in album["photos"]:
            photos[photo["id"]] = {
                "path": f'{folders[album["id"]]}/{names[photo["id"]]}',
                "version": photo.get("md5Checksum") or [photo.get("modifiedTime"), photo.get("size")],
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


def _read_manifest():
    try:
        manifest = json.loads((CACHE_DIR / MANIFEST).read_text())
        if manifest.get("schema") != 1:
            raise ValueError("Unknown manifest schema")
        for entry in manifest["photos"].values():
            _cache_path(entry["path"])
            entry["version"]
        for folder in manifest["folders"].values():
            _cache_path(f"{folder}/placeholder")
        return manifest
    except FileNotFoundError:
        pass
    except (OSError, ValueError, KeyError, TypeError, AttributeError):
        logger.warning("Cache manifest unavailable or invalid; rebuilding it")
    return {"photos": {}, "folders": {}}


def sync_photos(new_photos=None):
    with _sync_lock:
        try:
            _sync_photos(new_photos)
        except Exception:
            logger.exception("Photo sync failed; will retry on the next interval")


def _sync_photos(new_photos):
    CACHE_DIR.mkdir(parents=True, exist_ok=True)
    # No cache mutations until every folder and every listing page succeeds.
    try:
        catalog = _catalog(list_albums(GOOGLE_DRIVE_FOLDER_ID))
    except Exception:
        logger.exception("Photo sync failed while listing Google Drive albums")
        return
    previous = _read_manifest()
    digest = hashlib.sha256(json.dumps(catalog, sort_keys=True).encode()).hexdigest()
    for folder in catalog["folders"].values():
        _cache_path(f"{folder}/placeholder").parent.mkdir(exist_ok=True)
    if previous.get("hash") == digest and all(
        _cache_path(entry["path"]).is_file() for entry in catalog["photos"].values()
    ):
        logger.debug("Photo sync completed with no changes")
        return

    completed = {}
    target_owners = {entry["path"]: file_id for file_id, entry in catalog["photos"].items()}
    changed = 0
    failed = 0
    with TemporaryDirectory(prefix=".sync-", dir=CACHE_DIR) as staging:
        # Stage reusable files first so swaps of names/folders cannot overwrite
        # another photo before it has been relocated.
        reused = {}
        for file_id, entry in catalog["photos"].items():
            old = previous["photos"].get(file_id)
            if old and old["version"] == entry["version"] and old["path"] != entry["path"]:
                source = _cache_path(old["path"])
                if source.is_file():
                    staged = Path(staging) / str(len(reused))
                    shutil.copyfile(source, staged)
                    reused[file_id] = staged

        for file_id, entry in catalog["photos"].items():
            destination = _cache_path(entry["path"])
            old = previous["photos"].get(file_id)
            if old == entry and destination.is_file():
                completed[file_id] = entry
                continue
            temporary = destination.with_name(destination.name + ".part")
            try:
                if file_id in reused:
                    reused[file_id].replace(temporary)
                else:
                    logger.info("Downloading %s", entry["path"])
                    download_photo(file_id, temporary)
                temporary.replace(destination)
                completed[file_id] = entry
                changed += 1
                if new_photos is not None:
                    new_photos.put(destination)
            except Exception:
                failed += 1
                logger.exception("Failed to cache %s", entry["path"])
                temporary.unlink(missing_ok=True)
                # Retain an older copy until its replacement succeeds.
                if (old and target_owners.get(old["path"], file_id) == file_id
                        and _cache_path(old["path"]).is_file()):
                    completed[file_id] = old

    retained_paths = {entry["path"] for entry in completed.values()}
    for old in previous["photos"].values():
        if old["path"] not in retained_paths:
            _cache_path(old["path"]).unlink(missing_ok=True)
            changed += 1
    folders = dict(catalog["folders"])
    for folder_id, folder in previous["folders"].items():
        if folder not in folders.values():
            path = _cache_path(f"{folder}/placeholder").parent
            try:
                path.rmdir()
                changed += 1
            except FileNotFoundError:
                pass
            except OSError:
                # Keep tracking nonempty old folders for cleanup after a retry.
                retained_id = folder_id if folder_id.startswith("retained:") else f"retained:{folder_id}"
                folders[retained_id] = folder
    manifest = {"schema": 1, "folders": folders, "photos": completed,
                "hash": digest if not failed else None}
    temporary_manifest = CACHE_DIR / (MANIFEST + ".part")
    temporary_manifest.write_text(json.dumps(manifest, sort_keys=True), encoding="utf-8")
    temporary_manifest.replace(CACHE_DIR / MANIFEST)
    log = logger.info if changed or failed else logger.debug
    log("Photo sync completed: %d remote, %d changes, %d failed", len(catalog["photos"]), changed, failed)


if __name__ == "__main__":
    configure_logging()
    sync_photos()
