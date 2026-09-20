"""Transient messages and a persistent network warning in mpv OSD."""

import math
import time


class SlideshowOverlay:
    def __init__(self, player, url: str | None, seconds: int):
        self.player = player
        self._network_problem = False
        self._network_text = None
        self._notice = None
        self.deadline = None
        self._rendered = None
        self._set_message(f"Control: {url}" if url else None, seconds)

    def _set_message(self, text: str | None, seconds: int):
        self._notice = (text, time.monotonic() + seconds) if text and seconds else None
        self._render_active()

    def _render_active(self):
        self.deadline = None
        if self._network_problem:
            text = self._network_text or "Network connection problem. Retrying..."
            rendered = (text, "red")
        elif self._notice is not None and time.monotonic() < self._notice[1]:
            text, self.deadline = self._notice
            rendered = (text, "white")
        else:
            rendered = None
        if rendered == self._rendered:
            return
        if rendered is None:
            self.player.clear_overlay(1)
        else:
            self.player.set_overlay(1, rendered[0], color=rendered[1])
        self._rendered = rendered

    def show_message(self, text: str, seconds: int):
        self._notice = (text, time.monotonic() + seconds) if text and seconds else None
        if not self._network_problem:
            self._render_active()

    def set_network_problem(self, active: bool):
        if active == self._network_problem:
            return
        self._network_problem = active
        self._network_text = None
        self._render_active()

    def set_network_message(self, text):
        if text == self._network_text and bool(text) == self._network_problem:
            return
        self._network_problem = bool(text)
        self._network_text = text
        self._render_active()

    def new_frame(self):
        # mpv overlays are independent of the underlying image and survive a load.
        # _render_active is intentionally idempotent: a photo change must not
        # submit unchanged text and make it visibly refresh.
        self._render_active()

    def update(self):
        if self.deadline is not None and time.monotonic() >= self.deadline:
            self._notice = None
            self._render_active()

    def wait(self, milliseconds: int):
        if self.deadline is not None:
            remaining = max(0, math.ceil((self.deadline - time.monotonic()) * 1000))
            milliseconds = min(milliseconds, remaining)
        self.player.wait(max(1, milliseconds))
        self.update()
