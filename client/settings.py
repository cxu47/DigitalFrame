"""Validated settings shared by the web server and display thread."""

import re
from threading import Lock


INTEGER_ERROR = "Enter a positive whole number of seconds, such as 5."


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
    def __init__(self, display_seconds: int, *, folders=lambda: []):
        self._lock = Lock()
        self._folders = folders
        self._selected_folder = None
        self._revision = -1
        self._notification_revision = -1
        self._notification = ""
        self.set_display_seconds(display_seconds)

    def folder_snapshot(self):
        folders = sorted(self._folders())
        with self._lock:
            if self._selected_folder is not None and self._selected_folder not in folders:
                self._selected_folder = None
                self._notify("Photo folder: All")
            return folders, self._selected_folder

    @property
    def selected_folder(self):
        return self.folder_snapshot()[1]

    def set_folder(self, folder):
        if folder is not None and folder not in self._folders():
            raise ValueError("Choose an existing folder or All.")
        with self._lock:
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

    def snapshot(self) -> tuple[int, int]:
        """Return the value and accepted-update revision together."""
        with self._lock:
            return self._display_seconds, self._revision

    def set_display_seconds(self, value: int) -> None:
        if type(value) is not int or value <= 0:
            raise ValueError(INTEGER_ERROR)
        with self._lock:
            self._display_seconds = value
            self._revision += 1
            self._notify(f"Seconds per photo: {value}")
