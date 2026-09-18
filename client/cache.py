"""Shared photo format policy and a periodically refreshed local directory index."""

from dataclasses import dataclass
from datetime import datetime, timezone
import json
from pathlib import Path
from threading import Lock
import time

SOURCE_PHOTO_SUFFIXES = {".jpg", ".jpeg", ".png", ".webp", ".heic", ".heif"}
PLAYBACK_PHOTO_SUFFIXES = {".jpg", ".jpeg", ".png", ".webp"}
MANIFEST = ".photos.json"


def drive_time(value):
    """Parse Drive timestamps without letting damaged metadata stop playback."""
    if not isinstance(value, str):
        return None
    try:
        parsed = datetime.fromisoformat(value)
        return parsed.astimezone(timezone.utc) if parsed.tzinfo is not None else None
    except (ValueError, OverflowError):
        return None


def newest_first(value):
    created = drive_time(value)
    return -created.timestamp() if created is not None else float("inf")


def photo_month(value):
    """Return a stable UTC YYYY-MM bucket for a Drive creation timestamp."""
    created = drive_time(value)
    return created.strftime("%Y-%m") if created is not None else None


def valid_photo_month(value):
    return (isinstance(value, str) and len(value) == 7 and value[4] == "-"
            and value[:4].isdigit() and value[5:].isdigit()
            and 1 <= int(value[5:]) <= 12)


def photo_month_label(value):
    if not valid_photo_month(value):
        raise ValueError("Invalid photo month")
    return f"{value[5:]}-{value[:4]}"


def _read_catalog(cache):
    try:
        catalog = json.loads((cache / MANIFEST).read_text(encoding="utf-8"))
    except (OSError, ValueError, UnicodeError):
        return {}
    return catalog if isinstance(catalog, dict) else {}


def _entries(catalog, key):
    entries = catalog.get(key, {})
    return entries if isinstance(entries, dict) else {}


def _photo_metadata(catalog):
    return {entry["path"]: entry for entry in _entries(catalog, "photos").values()
            if isinstance(entry, dict) and isinstance(entry.get("path"), str)}


@dataclass(frozen=True)
class FolderDetails:
    count: int
    updated: datetime | None


@dataclass(frozen=True)
class PhotoArrival:
    path: Path
    month: str | None


def _latest(entry):
    return max((date for field in ("created", "modified")
                if (date := drive_time(entry.get(field))) is not None), default=None)


def supported_photo(name):
    return Path(name).suffix.lower() in SOURCE_PHOTO_SUFFIXES


def iphone_photo(name):
    return Path(name).suffix.lower() in {".heic", ".heif"}


def cached_folders(cache):
    try:
        return sorted(p.name for p in cache.iterdir()
                      if not p.name.startswith(".") and not p.is_symlink() and p.is_dir())
    except FileNotFoundError:
        return []


def cached_photos(cache, folders=None, *, catalog=None, source_formats=False):
    folders = cached_folders(cache) if folders is None else folders
    metadata = _photo_metadata(_read_catalog(cache) if catalog is None else catalog)
    suffixes = SOURCE_PHOTO_SUFFIXES if source_formats else PLAYBACK_PHOTO_SUFFIXES
    photos = (p for folder in folders for p in (cache / folder).glob("*")
              if not p.is_symlink() and p.is_file() and p.suffix.lower() in suffixes)
    # Unknown dates follow known dates; names break ties consistently offline.
    return sorted(photos, key=lambda p: (
        newest_first(metadata.get(p.relative_to(cache).as_posix(), {}).get("created")), p))


class CacheIndex:
    def __init__(self, cache, interval=1.0):
        self.cache = cache
        self.interval = interval
        self._lock = Lock()
        self._next_refresh = 0
        self._folders = []
        self._photos = []
        self._months = []
        self._photo_months = {}
        self._month_counts = {}
        self._details = {}

    def refresh(self, force=False):
        with self._lock:
            if force or time.monotonic() >= self._next_refresh:
                folders = cached_folders(self.cache)
                catalog = _read_catalog(self.cache)
                photos = cached_photos(self.cache, folders, catalog=catalog)
                metadata = _photo_metadata(catalog)
                folder_metadata = _entries(catalog, "folder_metadata")
                counts = dict.fromkeys(folders, 0)
                dates = {folder: [] for folder in folders}
                photo_months = {}
                for folder in folders:
                    entry = folder_metadata.get(folder, {})
                    if isinstance(entry, dict) and (date := _latest(entry)) is not None:
                        dates[folder].append(date)
                for photo in photos:
                    folder = photo.parent.name
                    counts[folder] += 1
                    entry = metadata.get(photo.relative_to(self.cache).as_posix(), {})
                    month = entry.get("month")
                    if not valid_photo_month(month):
                        month = photo_month(entry.get("created"))
                    if month is not None:
                        photo_months[photo] = month
                    if (date := _latest(entry)) is not None:
                        dates[folder].append(date)
                self._details = {folder: FolderDetails(counts[folder], max(dates[folder], default=None))
                                 for folder in folders}
                self._details[None] = FolderDetails(len(photos), max(
                    (date for values in dates.values() for date in values), default=None))
                self._folders, self._photos = folders, photos
                self._photo_months = photo_months
                self._months = sorted(set(photo_months.values()), reverse=True)
                self._month_counts = {
                    month: sum(value == month for value in photo_months.values())
                    for month in self._months
                }
                self._next_refresh = time.monotonic() + self.interval

    def folders(self):
        self.refresh()
        with self._lock:
            return list(self._folders)

    def photos(self, months=None):
        self.refresh()
        with self._lock:
            if months is None:
                return list(self._photos)
            selected = set(months)
            return [photo for photo in self._photos
                    if self._photo_months.get(photo) in selected]

    def months(self):
        self.refresh()
        with self._lock:
            return list(self._months)

    def month_counts(self):
        self.refresh()
        with self._lock:
            return dict(self._month_counts)

    def month_for(self, photo):
        self.refresh()
        with self._lock:
            return self._photo_months.get(photo)

    def folder_details(self):
        self.refresh()
        with self._lock:
            return dict(self._details)
