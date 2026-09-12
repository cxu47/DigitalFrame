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
    def __init__(self, display_seconds: int):
        self._lock = Lock()
        self._revision = -1
        self.set_display_seconds(display_seconds)

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
