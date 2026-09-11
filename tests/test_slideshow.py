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
    ticks = count(0, 100)
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
