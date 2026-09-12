"""Check actual banner pixels and expiration with a fake clock and dummy SDL."""

import pytest

from client import overlay


@pytest.fixture
def clock(monkeypatch):
    seconds = [100.0]
    monkeypatch.setattr(overlay.time, "monotonic", lambda: seconds[0])
    return seconds


def pixels(screen):
    return overlay.pygame.image.tobytes(screen, "RGB")


def test_url_is_at_top_left_and_restores_photo_at_deadline(screen, clock):
    screen.fill("red")
    original = pixels(screen)
    banner = overlay.ControlUrlOverlay(screen, "http://192.168.1.42:8000", 30)
    banner.new_frame()
    assert pixels(screen) != original
    assert banner.rect.topleft == (8, 8)
    assert banner.rect.right <= screen.get_width()
    assert screen.get_at((8, 8))[:3] == (0, 0, 0)
    assert screen.get_at((0, 0))[:3] == (255, 0, 0)
    clock[0] = 129.99
    banner.update()
    assert pixels(screen) != original
    clock[0] = 130
    banner.update()
    assert pixels(screen) == original
    assert banner.background is None


def test_expiration_restores_latest_photo_and_does_not_reset_for_each_photo(screen, clock):
    screen.fill("red")
    banner = overlay.ControlUrlOverlay(screen, "http://192.168.1.42:8000", 30)
    banner.new_frame()
    clock[0] = 120
    screen.fill("blue")
    latest = pixels(screen)
    banner.new_frame()
    assert pixels(screen) != latest
    clock[0] = 130
    banner.update()
    assert pixels(screen) == latest
    screen.fill("green")
    later = pixels(screen)
    banner.new_frame()
    assert pixels(screen) == later


@pytest.mark.parametrize("url,seconds", [(None, 30), ("http://192.168.1.42:8000", 0)])
def test_missing_address_or_disabled_overlay_leaves_pixels_unchanged(screen, clock, url, seconds):
    screen.fill("red")
    original = pixels(screen)
    banner = overlay.ControlUrlOverlay(screen, url, seconds)
    banner.new_frame()
    banner.update()
    assert pixels(screen) == original


def test_wait_is_shortened_to_remove_banner_on_time(screen, clock, monkeypatch):
    screen.fill("red")
    original = pixels(screen)
    banner = overlay.ControlUrlOverlay(screen, "http://192.168.1.42:8000", 30)
    banner.new_frame()
    waits = []

    def wait(milliseconds):
        waits.append(milliseconds)
        clock[0] += milliseconds / 1000

    monkeypatch.setattr(overlay.pygame.time, "wait", wait)
    banner.wait(60000)
    assert waits == [30000]
    assert pixels(screen) == original


@pytest.mark.parametrize("empty_cache", [False, True])
def test_slideshow_removes_banner_during_long_photo_or_waiting_screen(app, clock, monkeypatch, empty_cache):
    slideshow = app.slideshow
    observed = []
    painted = []
    from client.settings import RuntimeSettings

    monkeypatch.setattr(slideshow, "get_cached_photos", lambda: [] if empty_cache else ["a"])
    monkeypatch.setattr(slideshow.pygame.time, "get_ticks", lambda: int(clock[0] * 1000))
    monkeypatch.setattr(slideshow, "handle_events", lambda: clock[0] < 131)
    monkeypatch.setattr(slideshow, "IDLE_SECONDS", 1)

    def draw(screen, *args):
        screen.fill("red")
        painted.append(clock[0])
        return True

    monkeypatch.setattr(slideshow, "display_photo", draw)
    monkeypatch.setattr(slideshow, "display_message", draw)

    def wait(milliseconds):
        screen = slideshow.pygame.display.get_surface()
        observed.append((clock[0], screen.get_at((8, 8))[:3]))
        clock[0] += milliseconds / 1000
        assert clock[0] < 135

    monkeypatch.setattr(slideshow.pygame.time, "wait", wait)
    slideshow.show_slideshow(RuntimeSettings(60), control_url="http://192.168.1.42:8000",
                             url_display_seconds=30)
    assert (100, (0, 0, 0)) in observed
    assert (130, (255, 0, 0)) in observed
    if not empty_cache:
        assert painted == [100]
    assert not slideshow.pygame.get_init()
