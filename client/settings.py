"""Validated settings shared by the web server and display thread."""

import logging
import os
from pathlib import Path
import re
from threading import Lock

from dotenv import set_key


INTEGER_ERROR = "Enter a positive whole number of seconds, such as 5."
logger = logging.getLogger(__name__)


class SettingsPersistenceError(Exception):
    """A sanitized error suitable for the control panel."""


def parse_display_seconds(value: str | None) -> int:
    if not isinstance(value, str) or not re.fullmatch(r"[0-9]+", value.strip()):
        raise ValueError(INTEGER_ERROR)
    try:
        seconds = int(value.strip())
    except ValueError:
        raise ValueError(INTEGER_ERROR) from None
    if seconds <= 0:
        raise ValueError(INTEGER_ERROR)
    return seconds


class RuntimeSettings:
    def __init__(self, display_seconds: int, *, folders=lambda: [], selected_folder=None,
                 env_path=None):
        if type(display_seconds) is not int or display_seconds <= 0:
            raise ValueError(INTEGER_ERROR)
        if selected_folder is not None and not isinstance(selected_folder, str):
            raise ValueError("Saved photo folder must be text or All.")
        self._lock = Lock()
        self._folders = folders
        self._env_path = Path(env_path) if env_path is not None else None
        self._display_seconds = display_seconds
        self._selected_folder = selected_folder
        self._notification_revision = -1
        self._notification = ""
        self._notify(f"Seconds per photo: {self._display_seconds}")

    def _save_env_locked(self, key, value):
        if self._env_path is None:
            return
        try:
            self._env_path.parent.mkdir(parents=True, exist_ok=True)
            set_key(self._env_path, key, value, quote_mode="always")
            # Keep this process consistent with the file. The restart path
            # removes these inherited values so python-dotenv reloads them.
            os.environ[key] = value
        except (OSError, ValueError):
            logger.exception("Slideshow setting %s could not be saved to .env", key)
            raise SettingsPersistenceError(
                "Unable to save slideshow settings. Check that the board's .env is writable."
            ) from None

    def folder_snapshot(self):
        folders = sorted(self._folders())
        with self._lock:
            if self._selected_folder is not None and self._selected_folder not in folders:
                self._selected_folder = None
                self._save_env_locked("SELECTED_FOLDER", "")
                self._notify("Photo folder: All")
            return folders, self._selected_folder

    @property
    def selected_folder(self):
        return self.folder_snapshot()[1]

    def set_folder(self, folder):
        if folder is not None and folder not in self._folders():
            raise ValueError("Choose an existing folder or All.")
        with self._lock:
            self._save_env_locked("SELECTED_FOLDER", folder or "")
            self._selected_folder = folder
            self._notify(f"Photo folder: {folder if folder is not None else 'All'}")

    def _notify(self, message):
        """Record the latest accepted change while holding the settings lock."""
        self._notification = message
        self._notification_revision += 1

    def notification_snapshot(self) -> tuple[str, int]:
        self.folder_snapshot()  # Also report automatic fallback after a folder disappears.
        with self._lock:
            return self._notification, self._notification_revision

    @property
    def display_seconds(self) -> int:
        with self._lock:
            return self._display_seconds

    def set_display_seconds(self, value: int) -> None:
        if type(value) is not int or value <= 0:
            raise ValueError(INTEGER_ERROR)
        with self._lock:
            self._save_env_locked("DISPLAY_SECONDS", str(value))
            self._display_seconds = value
            self._notify(f"Seconds per photo: {value}")
