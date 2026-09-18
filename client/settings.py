"""Validated settings shared by the web server and display thread."""

import logging
import os
from pathlib import Path
import re
from threading import Lock

from dotenv import set_key

from .cache import photo_month_label, valid_photo_month


INTEGER_ERROR = "Enter a positive whole number of seconds, such as 5."
MONTH_ERROR = "Choose one or more available months."
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


def parse_selected_months(value) -> tuple[str, ...]:
    if value is None or value == "":
        return ()
    values = value.split(",") if isinstance(value, str) else value
    try:
        months = tuple(dict.fromkeys(
            month.strip() if isinstance(month, str) else month for month in values))
    except TypeError:
        raise ValueError(MONTH_ERROR) from None
    if any(not valid_photo_month(month) for month in months):
        raise ValueError(MONTH_ERROR)
    return months


class RuntimeSettings:
    def __init__(self, display_seconds: int, *, folders=lambda: [], months=lambda: [],
                 selected_folder=None, selected_months=(), view_mode="folder", env_path=None):
        if type(display_seconds) is not int or display_seconds <= 0:
            raise ValueError(INTEGER_ERROR)
        if selected_folder is not None and not isinstance(selected_folder, str):
            raise ValueError("Saved photo folder must be text or All.")
        if view_mode not in {"folder", "months"}:
            raise ValueError("Saved viewing mode must be folder or months.")
        self._lock = Lock()
        self._folders = folders
        self._months = months
        self._env_path = Path(env_path) if env_path is not None else None
        self._display_seconds = display_seconds
        self._selected_folder = selected_folder
        self._selected_months = parse_selected_months(selected_months)
        self._view_mode = view_mode
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

    def selection_snapshot(self):
        folders = sorted(self._folders())
        months = sorted({month for month in self._months()
                         if valid_photo_month(month)}, reverse=True)
        with self._lock:
            if self._selected_folder is not None and self._selected_folder not in folders:
                self._selected_folder = None
                self._save_env_locked("SELECTED_FOLDER", "")
                if self._view_mode == "folder":
                    self._notify("Photo folder: All")
            selected_months = tuple(
                month for month in months if month in self._selected_months)
            if selected_months != self._selected_months:
                self._selected_months = selected_months
                self._save_env_locked("SELECTED_MONTHS", ",".join(selected_months))
                if self._view_mode == "months":
                    if selected_months:
                        self._notify(self._month_message(selected_months))
            if self._view_mode == "months" and not self._selected_months:
                self._view_mode = "folder"
                self._save_env_locked("VIEW_MODE", "folder")
                self._notify(f"Photo folder: {self._selected_folder or 'All'}")
            return (folders, self._selected_folder, months,
                    self._selected_months, self._view_mode)

    def folder_snapshot(self):
        folders, selected, _, _, _ = self.selection_snapshot()
        return folders, selected

    def month_snapshot(self):
        _, _, months, selected, _ = self.selection_snapshot()
        return months, selected

    @property
    def selected_months(self):
        return self.month_snapshot()[1]

    @property
    def view_mode(self):
        return self.selection_snapshot()[4]

    def playback_selection(self):
        _, folder, _, months, mode = self.selection_snapshot()
        return (mode, folder if mode == "folder" else None,
                months if mode == "months" else ())

    @property
    def selected_folder(self):
        return self.folder_snapshot()[1]

    def set_folder(self, folder):
        if folder is not None and folder not in self._folders():
            raise ValueError("Choose an existing folder or All.")
        with self._lock:
            self._save_env_locked("SELECTED_FOLDER", folder or "")
            self._save_env_locked("VIEW_MODE", "folder")
            self._selected_folder = folder
            self._view_mode = "folder"
            self._notify(f"Photo folder: {folder if folder is not None else 'All'}")

    @staticmethod
    def _month_message(months):
        return "Photo months: " + ", ".join(photo_month_label(month) for month in months)

    def set_months(self, selected):
        selected = parse_selected_months(selected)
        available = sorted({month for month in self._months()
                            if valid_photo_month(month)}, reverse=True)
        if not selected or any(month not in available for month in selected):
            raise ValueError(MONTH_ERROR)
        requested = set(selected)
        selected = tuple(month for month in available if month in requested)
        with self._lock:
            self._save_env_locked("SELECTED_MONTHS", ",".join(selected))
            self._save_env_locked("VIEW_MODE", "months")
            self._selected_months = selected
            self._view_mode = "months"
            self._notify(self._month_message(selected))

    def _notify(self, message):
        """Record the latest accepted change while holding the settings lock."""
        self._notification = message
        self._notification_revision += 1

    def notification_snapshot(self) -> tuple[str, int]:
        self.selection_snapshot()  # Also report automatic selection fallback.
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
