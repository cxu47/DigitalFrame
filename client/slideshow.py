"""Playlist policy for the fullscreen mpv photo renderer."""

import logging
import math
import os
import time
from collections import deque
from pathlib import Path
from queue import Empty
from tempfile import NamedTemporaryFile
from threading import Event, Lock, Thread

from .cache import PLAYBACK_PHOTO_SUFFIXES, cached_folders, cached_photos
from .config import CACHE_DIR, DISPLAY_SECONDS, IDLE_SECONDS
from .overlay import SlideshowOverlay
from .player import MPVPlayer
from .settings import RuntimeSettings


logger = logging.getLogger(__name__)


class PhotoReadAhead:
    """Copy exactly one upcoming compressed photo into a temporary buffer."""

    def __init__(self, path):
        self.path = path
        self._buffer_path = None
        self._released = False
        self._lock = Lock()
        self._ready = Event()
        Thread(target=self._read, name="photo-read-ahead", daemon=True).start()

    def _read(self):
        temporary = None
        try:
            memory_dir = Path("/dev/shm")
            directory = (memory_dir if memory_dir.is_dir()
                         and os.access(memory_dir, os.W_OK) else None)
            with self.path.open("rb") as source, NamedTemporaryFile(
                mode="wb", prefix="digitalframe-", suffix=self.path.suffix,
                dir=directory, delete=False,
            ) as destination:
                temporary = Path(destination.name)
                while chunk := source.read(1024 * 1024):
                    destination.write(chunk)
            with self._lock:
                if not self._released:
                    self._buffer_path = temporary
                    temporary = None
        except OSError:
            # Normal playback reports missing/replaced files and skips them.
            pass
        finally:
            if temporary is not None:
                temporary.unlink(missing_ok=True)
            self._ready.set()

    @property
    def ready(self):
        return self._ready.is_set()

    @property
    def playback_path(self):
        with self._lock:
            return self._buffer_path or self.path

    def release(self):
        with self._lock:
            self._released = True
            temporary, self._buffer_path = self._buffer_path, None
        if temporary is not None:
            temporary.unlink(missing_ok=True)


def get_cached_folders():
    return cached_folders(CACHE_DIR)


def get_cached_photos():
    return cached_photos(CACHE_DIR)


def display_message(player, message):
    player.stop()
    player.set_overlay(2, message, position="center")


def display_photo(player, photo_path, prepared=None):
    try:
        player.load(prepared or photo_path)
        logger.debug("Displayed photo: %s", photo_path.name)
        return True
    except Exception as exc:
        logger.warning("Skipping unavailable image %s: %s", photo_path.name, exc)
        return False


def show_slideshow(settings=None, *, control_url=None, url_display_seconds=30,
                   new_photos=None, status=None, index=None, network=None,
                   stop_event=None):
    if settings is None:
        settings = RuntimeSettings(DISPLAY_SECONDS, folders=get_cached_folders)
    player = None
    bad_photos = {}
    running = True
    try:
        player = MPVPlayer()
        logger.info("Slideshow started")
        current_url = control_url() if callable(control_url) else control_url
        overlay = SlideshowOverlay(player, current_url, url_display_seconds)
        observed_revision = 0

        def check():
            nonlocal running, observed_revision, current_url
            if stop_event is not None and stop_event.is_set():
                running = False
                return False
            if callable(control_url):
                url = control_url()
                if url and url != current_url:
                    current_url = url
                    overlay.show_message(f"Control: {url}", url_display_seconds)
            if network is not None:
                overlay.set_network_message(network.snapshot().banner(
                    current_url if not callable(control_url) else control_url(), network.control_port))
            elif status is not None:
                overlay.set_network_problem(status.network_problem())
            message, revision = settings.notification_snapshot()
            if revision != observed_revision:
                overlay.show_message(message, 15)
                observed_revision = revision
            overlay.update()
            running = player.running
            return running

        def pause(milliseconds):
            overlay.wait(max(1, min(int(IDLE_SECONDS * 1000), milliseconds)))

        def eligible(path, folder):
            try:
                valid = (path.parent.parent == CACHE_DIR and path.is_file()
                         and not path.is_symlink() and not path.parent.is_symlink()
                         and path.suffix.lower() in PLAYBACK_PHOTO_SUFFIXES
                         and (folder is None or path.parent.name == folder))
                failed = bad_photos.get(path)
                signature = (path.stat().st_size, path.stat().st_mtime_ns)
                if failed and (failed[0] != signature or time.monotonic() >= failed[1]):
                    bad_photos.pop(path, None)
                    failed = None
                return valid and not failed
            except OSError:
                return False

        while running and check():
            selected = settings.selected_folder
            photos = index.photos() if index is not None else get_cached_photos()
            bad_photos = {path: value for path, value in bad_photos.items() if path in photos}
            remaining = deque(path for path in photos if eligible(path, selected))
            seen = set()
            priority_paths = set()
            successes = 0
            failures = 0

            def queued():
                if new_photos is None:
                    return None
                while True:
                    try:
                        path = new_photos.get_nowait()
                    except Empty:
                        return None
                    if (path.suffix.lower() in PLAYBACK_PHOTO_SUFFIXES and path not in seen
                            and eligible(path, selected)):
                        seen.add(path)
                        priority_paths.add(path)
                        return path

            def next_photo():
                path = queued()
                if path is not None:
                    return path
                while remaining:
                    path = remaining.popleft()
                    if path not in seen and eligible(path, selected):
                        seen.add(path)
                        return path
                return None

            path = next_photo()
            read_ahead = None
            while path is not None and running:
                if settings.selected_folder != selected:
                    break
                urgent = queued() if path not in priority_paths else None
                if urgent is not None:
                    remaining.appendleft(path)
                    seen.discard(path)
                    path = urgent
                    if read_ahead is not None:
                        read_ahead.release()
                    read_ahead = PhotoReadAhead(path)
                while read_ahead is not None and not read_ahead.ready and running:
                    if not check():
                        break
                    # Keep the current frame visible while the sole look-ahead
                    # buffer finishes, without making controls feel sluggish.
                    pause(100)
                if not running or settings.selected_folder != selected:
                    if read_ahead is not None:
                        read_ahead.release()
                        read_ahead = None
                    break
                success = display_photo(
                    player, path,
                    read_ahead.playback_path if read_ahead is not None else None,
                )
                if read_ahead is not None:
                    read_ahead.release()
                    read_ahead = None
                if success:
                    successes += 1
                    overlay.new_frame()
                else:
                    failures += 1
                    try:
                        bad_photos[path] = ((path.stat().st_size, path.stat().st_mtime_ns),
                                            time.monotonic() + 60)
                    except OSError:
                        pass
                    if status is not None:
                        status.report("Photos", f"Cannot display {path.name}. Drive sync will check the cached file.")
                    if not player.running:
                        running = False
                        break
                deadline = time.monotonic() + settings.display_seconds
                path = next_photo()
                if success and path is not None:
                    read_ahead = PhotoReadAhead(path)
                if success:
                    while running:
                        remaining_time = deadline - time.monotonic()
                        buffering = read_ahead is not None and not read_ahead.ready
                        if remaining_time <= 0 and not buffering:
                            break
                        if not check():
                            break
                        pause(max(1, math.ceil(remaining_time * 1000))
                              if remaining_time > 0 else 100)
            if read_ahead is not None:
                read_ahead.release()
            if not running:
                break
            if settings.selected_folder != selected:
                continue
            if successes == 0:
                display_message(player, "No readable photos available. Waiting for photos.")
                overlay.new_frame()
                if check():
                    pause(max(1000, int(IDLE_SECONDS * 1000)))
            elif failures == 0 and not bad_photos and status is not None:
                status.clear("Photos")
    finally:
        if player is not None:
            player.close()
        logger.info("Slideshow stopped")


if __name__ == "__main__":
    from .runtime import main
    main()
