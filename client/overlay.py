"""Transient messages and a persistent network warning in the same banner."""

import math
import time

import pygame


class SlideshowOverlay:
    def __init__(self, screen, url: str | None, seconds: int):
        self.screen = screen
        self.background = None
        self._network_problem = False
        self._network_text = None
        self._notice = None
        self._set_message(f"Control: {url}" if url else None, seconds)

    def _set_message(self, text: str | None, seconds: int):
        self._notice = (text, time.monotonic() + seconds) if text and seconds else None
        self._render_active()

    def _render_active(self):
        self.label = None
        self.deadline = None
        if self._network_problem:
            text = self._network_text or "Network connection problem. Retrying..."
            color = "red"
        elif self._notice is not None and time.monotonic() < self._notice[1]:
            text, self.deadline = self._notice
            color = "white"
        else:
            return
        font = pygame.font.Font(None, 28)
        available = max(1, self.screen.get_width() - 24)
        if "\n" in text:
            # Keep setup credentials legible by wrapping individual lines instead
            # of shrinking the entire banner into one long line.
            for size in (28, 24, 20, 16, 12):
                font = pygame.font.Font(None, size)
                lines = []
                for paragraph in text.splitlines():
                    line = ""
                    for character in paragraph:
                        if line and font.size(line + character)[0] > available:
                            lines.append(line)
                            line = ""
                        line += character
                    lines.append(line)
                if len(lines) * font.get_linesize() <= max(1, self.screen.get_height() - 24):
                    break
            self.label = pygame.Surface((available, max(1, len(lines) * font.get_linesize())))
            self.label.fill("black")
            for number, line in enumerate(lines):
                self.label.blit(font.render(line, True, color), (0, number * font.get_linesize()))
        else:
            self.label = font.render(text, True, color)
        if self.label.get_width() > available:
            scale = available / self.label.get_width()
            self.label = pygame.transform.smoothscale(
                self.label, (available, max(1, int(self.label.get_height() * scale))),
            )
        self.rect = self.label.get_rect(topleft=(12, 12)).inflate(8, 8)
        self.rect = self.rect.clip(self.screen.get_rect())

    def show_message(self, text: str, seconds: int):
        if self._network_problem:
            # Settings still apply, but cannot hide the connection warning.
            self._notice = (text, time.monotonic() + seconds) if text and seconds else None
            return
        # Restore the entire previous rectangle before replacing it, since the
        # next message may be shorter. Only the display thread calls this.
        self._restore_background()
        self._set_message(text, seconds)
        self.new_frame()

    def set_network_problem(self, active: bool):
        if active == self._network_problem:
            return
        self._restore_background()
        self._network_problem = active
        self._network_text = None
        self._render_active()
        self.new_frame()

    def set_network_message(self, text):
        if text == self._network_text and bool(text) == self._network_problem:
            return
        self._restore_background()
        self._network_problem = bool(text)
        self._network_text = text
        self._render_active()
        self.new_frame()

    def _restore_background(self):
        if self.background is not None:
            self.screen.blit(self.background, self.rect)
            self.background = None
            pygame.display.update(self.rect)

    def new_frame(self):
        # The caller has just redrawn the base frame, replacing any old banner.
        self.background = None
        if self.label is None or (self.deadline is not None and time.monotonic() >= self.deadline):
            return
        self.background = self.screen.subsurface(self.rect).copy()
        self.screen.fill("black", self.rect)
        self.screen.blit(self.label, (12, 12))
        pygame.display.update(self.rect)

    def update(self):
        if self.background is not None and self.deadline is not None and time.monotonic() >= self.deadline:
            self._restore_background()

    def wait(self, milliseconds: int):
        # Do not leave the banner visible past its deadline if IDLE_SECONDS is
        # longer than the remaining banner time. Photo timing is independent.
        if self.background is not None and self.deadline is not None:
            remaining = max(0, math.ceil((self.deadline - time.monotonic()) * 1000))
            milliseconds = min(milliseconds, remaining)
        pygame.time.wait(milliseconds)
        self.update()
