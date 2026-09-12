"""Temporary slideshow messages sharing one banner and pixel restoration path."""

import math
import time

import pygame


class SlideshowOverlay:
    def __init__(self, screen, url: str | None, seconds: int):
        self.screen = screen
        self.background = None
        self._set_message(f"Control: {url}" if url else None, seconds)

    def _set_message(self, text: str | None, seconds: int):
        self.label = None
        if not text or seconds == 0:
            return
        self.deadline = time.monotonic() + seconds
        font = pygame.font.Font(None, 28)
        self.label = font.render(text, True, "white")
        available = max(1, self.screen.get_width() - 24)
        if self.label.get_width() > available:
            scale = available / self.label.get_width()
            self.label = pygame.transform.smoothscale(
                self.label, (available, max(1, int(self.label.get_height() * scale))),
            )
        self.rect = self.label.get_rect(topleft=(12, 12)).inflate(8, 8)
        self.rect = self.rect.clip(self.screen.get_rect())

    def show_message(self, text: str, seconds: int):
        # Restore the entire previous rectangle before replacing it, since the
        # next message may be shorter. Only the display thread calls this.
        self._restore_background()
        self._set_message(text, seconds)
        self.new_frame()

    def _restore_background(self):
        if self.background is not None:
            self.screen.blit(self.background, self.rect)
            self.background = None
            pygame.display.update(self.rect)

    def new_frame(self):
        # The caller has just redrawn the base frame, replacing any old banner.
        self.background = None
        if self.label is None or time.monotonic() >= self.deadline:
            return
        self.background = self.screen.subsurface(self.rect).copy()
        self.screen.fill("black", self.rect)
        self.screen.blit(self.label, (12, 12))
        pygame.display.update(self.rect)

    def update(self):
        if self.background is not None and time.monotonic() >= self.deadline:
            self._restore_background()

    def wait(self, milliseconds: int):
        # Do not leave the banner visible past its deadline if IDLE_SECONDS is
        # longer than the remaining banner time. Photo timing is independent.
        if self.background is not None:
            remaining = max(0, math.ceil((self.deadline - time.monotonic()) * 1000))
            milliseconds = min(milliseconds, remaining)
        pygame.time.wait(milliseconds)
        self.update()
