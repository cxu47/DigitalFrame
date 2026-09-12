"""Render real images through Pillow and Pygame's headless display."""

from itertools import count

import pytest
from PIL import Image


@pytest.mark.parametrize("suffix,mode,size", [
    ("jpg", "RGB", (160, 40)),
    ("png", "RGBA", (20, 5)),
    ("webp", "RGB", (160, 40)),
    ("heic", "RGB", (160, 40)),
])
def test_photo_formats_fit_and_center_with_black_borders(app, screen, tmp_path, suffix, mode, size):
    photo = tmp_path / f"photo.{suffix}"
    with Image.new(mode, size, "red") as source:
        source.save(photo)

    assert app.slideshow.display_photo(screen, photo) is True
    for point in ((0, 20), (79, 39), (40, 30)):
        red, green, blue, _ = screen.get_at(point)
        assert red > 240 and green < 15 and blue < 15
    for point in ((40, 19), (40, 40)):
        assert screen.get_at(point)[:3] == (0, 0, 0)


def test_phone_exif_orientation_is_applied_before_fitting(app, screen, tmp_path):
    photo = tmp_path / "phone.jpg"
    with Image.new("RGB", (120, 60), "red") as source:
        source.paste("blue", (60, 0, 120, 60))
        exif = source.getexif()
        exif[274] = 6  # A phone photo needing a clockwise quarter turn.
        source.save(photo, exif=exif)

    assert app.slideshow.display_photo(screen, photo) is True
    assert screen.get_at((40, 10)).r > 240
    assert screen.get_at((40, 50)).b > 240
    assert screen.get_at((24, 30))[:3] == (0, 0, 0)
    assert screen.get_at((55, 30))[:3] == (0, 0, 0)


@pytest.mark.parametrize("display_size,photo_size,expected_size", [
    ((160, 90), (200, 100), (160, 80)),
    ((160, 90), (100, 200), (45, 90)),
    ((160, 90), (20, 20), (90, 90)),
    ((120, 90), (200, 100), (120, 60)),
    ((90, 160), (200, 100), (90, 45)),
    ((90, 160), (100, 200), (80, 160)),
    ((160, 90), (320, 180), (160, 90)),
])
def test_photo_proportions_on_different_displays(
    app, screen, tmp_path, display_size, photo_size, expected_size,
):
    pygame = app.slideshow.pygame
    surface = pygame.Surface(display_size)
    surface.fill("green")  # Old content must also be cleared from the bars.
    photo = tmp_path / "photo.png"
    with Image.new("RGB", photo_size, "red") as source:
        source.save(photo)

    assert app.slideshow.display_photo(surface, photo)
    expected = pygame.Rect((0, 0), expected_size)
    expected.topleft = (
        (display_size[0] - expected.width) // 2,
        (display_size[1] - expected.height) // 2,
    )
    for x in range(display_size[0]):
        for y in range(display_size[1]):
            color = (255, 0, 0) if expected.collidepoint(x, y) else (0, 0, 0)
            assert surface.get_at((x, y))[:3] == color


def test_slideshow_uses_current_display_resolution_fullscreen(app, monkeypatch):
    slideshow = app.slideshow
    pygame = slideshow.pygame
    pygame.init()
    desktop_size = pygame.display.get_desktop_sizes()[0]
    observed = []

    def message(screen, text):
        observed.append((screen.get_size(), bool(screen.get_flags() & pygame.FULLSCREEN)))

    monkeypatch.setattr(slideshow, "get_cached_photos", lambda: [])
    monkeypatch.setattr(slideshow, "display_message", message)
    monkeypatch.setattr(slideshow, "handle_events", lambda: False)
    slideshow.show_slideshow()

    assert observed == [(desktop_size, True)]
    assert not pygame.get_init()


def test_cache_selection_excludes_partial_files_and_directories(app):
    app.cache.mkdir()
    for name in ("b.PNG", "a.jpg", "c.heif", "photo.jpg.part", "notes.txt"):
        (app.cache / name).touch()
    (app.cache / "directory.jpg").mkdir()

    assert [p.name for p in app.slideshow.get_cached_photos()] == ["a.jpg", "b.PNG", "c.heif"]


def test_missing_and_corrupt_images_do_not_prevent_next_photo(app, screen, tmp_path):
    corrupt = tmp_path / "corrupt.jpg"
    corrupt.write_bytes(b"not a photo")
    valid = tmp_path / "valid.png"
    with Image.new("RGB", (20, 20), "red") as source:
        source.save(valid)

    assert app.slideshow.display_photo(screen, tmp_path / "missing.jpg") is False
    assert app.slideshow.display_photo(screen, corrupt) is False
    assert app.slideshow.display_photo(screen, valid) is True
    assert screen.get_at((40, 30))[:3] == (255, 0, 0)


@pytest.mark.parametrize("exit_event", ["escape", "close"])
def test_slideshow_waits_for_new_photos_cycles_and_exits_cleanly(app, monkeypatch, exit_event):
    slideshow = app.slideshow
    pygame = slideshow.pygame
    app.cache.mkdir()
    displayed = []
    messages = []
    ticks = count(0, 500)
    waits = []
    render = slideshow.display_photo
    render_message = slideshow.display_message

    def display(screen, path):
        success = render(screen, path)
        if success:
            displayed.append(path.name)
            if len(displayed) == 3:
                event = (pygame.event.Event(pygame.KEYDOWN, key=pygame.K_ESCAPE)
                         if exit_event == "escape" else pygame.event.Event(pygame.QUIT))
                pygame.event.post(event)
        return success

    def message(screen, text):
        messages.append(text)
        render_message(screen, text)

    def wait(milliseconds):
        waits.append(milliseconds)
        assert len(waits) < 20, "Slideshow did not progress or respond to exit"
        if len(waits) == 1:
            (app.cache / "0-broken.jpg").write_bytes(b"bad image")
            for name in ("a.png", "b.png"):
                with Image.new("RGB", (20, 10), "red") as source:
                    source.save(app.cache / name)

    monkeypatch.setattr(slideshow, "display_photo", display)
    monkeypatch.setattr(slideshow, "display_message", message)
    monkeypatch.setattr(pygame.time, "get_ticks", lambda: next(ticks))
    monkeypatch.setattr(pygame.time, "wait", wait)
    try:
        slideshow.show_slideshow()
        assert not pygame.get_init()
    finally:
        pygame.quit()

    assert len(messages) == 1
    assert displayed == ["a.png", "b.png", "a.png"]
    assert waits and all(delay == 10 for delay in waits)


@pytest.mark.parametrize("initial,updated", [(5, 10), (5, 1)])
def test_form_update_applies_to_next_photo_and_invalid_input_keeps_current_interval(
    app, monkeypatch, initial, updated,
):
    from fastapi.testclient import TestClient
    from client.control.app import create_app
    from client.settings import RuntimeSettings

    slideshow = app.slideshow
    settings = RuntimeSettings(initial)
    clock = [0]
    displayed = []
    changed = [False]
    monkeypatch.setattr(slideshow, "get_cached_photos", lambda: ["a", "b", "c"])
    monkeypatch.setattr(slideshow.pygame.time, "get_ticks", lambda: clock[0])

    def display(screen, path):
        displayed.append((path, clock[0]))
        return True

    with TestClient(create_app(settings)) as browser:
        def wait(milliseconds):
            clock[0] += 100
            if not changed[0]:
                invalid = browser.post("/settings", data={"display_seconds": "5.0"})
                assert invalid.status_code == 422
                assert settings.display_seconds == initial
                browser.post("/settings", data={"display_seconds": str(updated)})
                changed[0] = True
            assert clock[0] <= (initial + updated + 1) * 1000

        monkeypatch.setattr(slideshow, "display_photo", display)
        monkeypatch.setattr(slideshow, "handle_events", lambda: len(displayed) < 3)
        monkeypatch.setattr(slideshow.pygame.time, "wait", wait)
        slideshow.show_slideshow(settings)

    assert displayed == [("a", 0), ("b", initial * 1000), ("c", (initial + updated) * 1000)]
    assert not slideshow.pygame.get_init()


def test_update_while_cache_empty_applies_to_first_photo(app, monkeypatch):
    from fastapi.testclient import TestClient
    from client.control.app import create_app
    from client.settings import RuntimeSettings

    slideshow = app.slideshow
    settings = RuntimeSettings(5)
    clock = [0]
    photos = []
    shown = []
    monkeypatch.setattr(slideshow, "get_cached_photos", lambda: photos)
    monkeypatch.setattr(slideshow.pygame.time, "get_ticks", lambda: clock[0])
    monkeypatch.setattr(slideshow, "handle_events", lambda: len(shown) < 2)
    monkeypatch.setattr(slideshow, "display_photo", lambda screen, path: shown.append(clock[0]) or True)

    with TestClient(create_app(settings)) as browser:
        def wait(milliseconds):
            clock[0] += 100
            if not photos:
                browser.post("/settings", data={"display_seconds": "1"})
                photos.extend(["a", "b"])
            assert clock[0] < 2000

        monkeypatch.setattr(slideshow.pygame.time, "wait", wait)
        slideshow.show_slideshow(settings)
    assert shown == [100, 1100]


def test_display_initialization_error_releases_pygame(app, monkeypatch):
    def fail(size, flags):
        raise app.slideshow.pygame.error("display unavailable")

    monkeypatch.setattr(app.slideshow.pygame.display, "set_mode", fail)
    with pytest.raises(app.slideshow.pygame.error):
        app.slideshow.show_slideshow()
    assert not app.slideshow.pygame.get_init()
