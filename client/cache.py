"""Shared photo format policy and a periodically refreshed local directory index."""

from pathlib import Path
from threading import Lock
import time

SUPPORTED_PHOTO_SUFFIXES = {".jpg", ".jpeg", ".png", ".webp", ".heic", ".heif"}


def supported_photo(name):
    return Path(name).suffix.lower() in SUPPORTED_PHOTO_SUFFIXES


def cached_folders(cache):
    try:
        return sorted(p.name for p in cache.iterdir()
                      if not p.name.startswith(".") and not p.is_symlink() and p.is_dir())
    except FileNotFoundError:
        return []


def cached_photos(cache, folders=None):
    folders = cached_folders(cache) if folders is None else folders
    return sorted(p for folder in folders for p in (cache / folder).glob("*")
                  if not p.is_symlink() and p.is_file() and supported_photo(p.name))


class CacheIndex:
    def __init__(self, cache, interval=1.0):
        self.cache = cache
        self.interval = interval
        self._lock = Lock()
        self._next_refresh = 0
        self._folders = []
        self._photos = []

    def refresh(self, force=False):
        with self._lock:
            if force or time.monotonic() >= self._next_refresh:
                folders = cached_folders(self.cache)
                photos = cached_photos(self.cache, folders)
                self._folders, self._photos = folders, photos
                self._next_refresh = time.monotonic() + self.interval

    def folders(self):
        self.refresh()
        with self._lock:
            return list(self._folders)

    def photos(self):
        self.refresh()
        with self._lock:
            return list(self._photos)
