"""A temporary URL banner that restores only the pixels it covers."""

import math
import time

import pygame


class ControlUrlOverlay:
    def __init__(self, screen, url: str | None, seconds: int):
        self.screen = screen
        self.background = None
        self.label = None
        if not url or seconds == 0:
            return
        self.deadline = time.monotonic() + seconds
        font = pygame.font.Font(None, 28)
        self.label = font.render(f"Control: {url}", True, "white")
        available = max(1, screen.get_width() - 24)
        if self.label.get_width() > available:
            scale = available / self.label.get_width()
            self.label = pygame.transform.smoothscale(
                self.label, (available, max(1, int(self.label.get_height() * scale))),
            )
        self.rect = self.label.get_rect(topleft=(12, 12)).inflate(8, 8)
        self.rect = self.rect.clip(screen.get_rect())

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
            self.screen.blit(self.background, self.rect)
            self.background = None
            pygame.display.update(self.rect)

    def wait(self, milliseconds: int):
        # Do not leave the banner visible past its deadline if IDLE_SECONDS is
        # longer than the remaining banner time. Photo timing is independent.
        if self.background is not None:
            remaining = max(0, math.ceil((self.deadline - time.monotonic()) * 1000))
            milliseconds = min(milliseconds, remaining)
        pygame.time.wait(milliseconds)
        self.update()
