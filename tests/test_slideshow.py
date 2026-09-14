"""Render real images through Pillow and Pygame's headless display."""

from itertools import count
from pathlib import Path
from queue import SimpleQueue

import pytest

pytestmark = pytest.mark.usefixtures("immediate_loader")
from PIL import Image


@pytest.mark.parametrize("suffix,mode,size", [
    ("jpg", "RGB", (160, 40)),
    ("png", "RGBA", (20, 5)),
    ("webp", "RGB", (160, 40)),
    ("heic", "RGB", (160, 40)),
])
def test_photo_formats_fit_and_center_with_black_borders(app, screen, tmp_path, suffix, mode, size):
    photo = tmp_path / f"photo.{suffix}"
    if suffix == "heic":
        # Some board libheif builds decode HEIC but intentionally omit encoders.
        photo.write_bytes((Path(__file__).parent / "fixtures/wide-red.heic").read_bytes())
    else:
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
    monkeypatch.setattr(slideshow, "handle_events", lambda: not observed)
    slideshow.show_slideshow()

    assert observed == [(desktop_size, True)]
    assert not pygame.get_init()


def test_cache_selection_excludes_partial_files_and_directories(app):
    app.cache.mkdir()
    (app.cache / "loose.jpg").touch()
    album = app.cache / "kids"
    album.mkdir()
    for name in ("b.PNG", "a.jpg", "c.heif", "photo.jpg.part", "notes.txt"):
        (album / name).touch()
    (album / "directory.jpg").mkdir()
    (album / "directory.jpg" / "nested.jpg").touch()

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
    album = app.cache / "kids"
    album.mkdir(parents=True)
    displayed = []
    messages = []
    ticks = count(0, 500)
    waits = []
    render = slideshow.display_photo
    render_message = slideshow.display_message

    def display(screen, path, prepared=None):
        success = render(screen, path, prepared)
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
            (album / "0-broken.jpg").write_bytes(b"bad image")
            for name in ("a.png", "b.png"):
                with Image.new("RGB", (20, 10), "red") as source:
                    source.save(album / name)

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
    assert waits and all(0 < delay <= 10 for delay in waits)


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
    photos = [app.cache / "kids" / name for name in ("a", "b", "c")]
    photos[0].parent.mkdir(parents=True)
    for photo in photos:
        photo.touch()
    monkeypatch.setattr(slideshow, "get_cached_photos", lambda: photos)
    monkeypatch.setattr(slideshow.pygame.time, "get_ticks", lambda: clock[0])

    def display(screen, path, prepared=None):
        displayed.append((path.name, clock[0]))
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
    monkeypatch.setattr(slideshow, "display_photo", lambda screen, path, prepared=None: shown.append(clock[0]) or True)

    with TestClient(create_app(settings)) as browser:
        def wait(milliseconds):
            clock[0] += 100
            if not photos:
                browser.post("/settings", data={"display_seconds": "1"})
                (app.cache / "kids").mkdir(parents=True)
                photos.extend([app.cache / "kids" / name for name in ("a", "b")])
                for photo in photos:
                    photo.touch()
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


def test_sync_arrivals_play_next_then_resume_without_interrupting_current_photo(app, monkeypatch):
    slideshow = app.slideshow
    pygame = slideshow.pygame
    new_photos = SimpleQueue()
    album = app.cache / "kids"
    album.mkdir(parents=True)
    for name in ("a.png", "b.png", "c.png"):
        with Image.new("RGB", (20, 10), "red") as source:
            source.save(album / name)
    monkeypatch.setattr(app.sync, "list_albums", lambda folder, **kwargs: [{"id": "kids", "name": "kids", "photos": [
        *[{"id": p.stem, "name": p.name, "md5Checksum": __import__("hashlib").md5(p.read_bytes()).hexdigest()} for p in album.glob("[abc].png")],
        {"id": "z", "name": "z.png"},
        {"id": "broken", "name": "broken.png"},
        {"id": "aa", "name": "aa.png"},
    ]}])

    def download(file_id, path, **kwargs):
        if file_id == "broken":
            path.write_bytes(b"not an image")
        else:
            with Image.new("RGB", (20, 10), "blue") as source:
                source.save(path, format="PNG")

    clock = [0]
    displayed = []
    render = slideshow.display_photo

    def display(screen, path, prepared=None):
        success = render(screen, path, prepared)
        if success:
            displayed.append((path.name, clock[0]))
            if len(displayed) == 5:
                pygame.event.post(pygame.event.Event(pygame.QUIT))
        return success

    def wait(milliseconds):
        clock[0] += 100
        if clock[0] == 100:
            app.sync.sync_photos(new_photos)
        assert clock[0] <= 4000, "Slideshow failed to resume its normal rotation"

    monkeypatch.setattr(app.sync, "download_photo", download)
    monkeypatch.setattr(slideshow, "display_photo", display)
    monkeypatch.setattr(pygame.time, "get_ticks", lambda: clock[0])
    monkeypatch.setattr(pygame.time, "wait", wait)
    slideshow.show_slideshow(new_photos=new_photos)

    assert displayed == [
        ("a.png", 0), ("z.png", 1000), ("aa.png", 2000),
        ("b.png", 3000), ("c.png", 4000),
    ]
    assert {p.name for p in album.iterdir()} == {
        "a.png", "b.png", "c.png", "z.png", "aa.png", "broken.png",
    }


@pytest.mark.parametrize('selection', ['kids', 'empty'])
def test_folder_change_applies_at_next_photo_and_filters_queued_arrivals(app, monkeypatch, selection):
    from fastapi.testclient import TestClient
    from client.control.app import create_app
    from client.settings import RuntimeSettings

    slideshow = app.slideshow
    for folder, names in [('summer', ['a.jpg', 'b.jpg']), ('kids', ['a.jpg']), ('empty', [])]:
        directory = app.cache / folder
        directory.mkdir(parents=True)
        for name in names:
            (directory / name).touch()
    settings = RuntimeSettings(1, folders=slideshow.get_cached_folders)
    settings.set_folder('summer')
    queue = SimpleQueue()
    clock = [0]
    shown = []
    waiting = []
    monkeypatch.setattr(slideshow.pygame.time, 'get_ticks', lambda: clock[0])
    monkeypatch.setattr(slideshow, 'display_photo', lambda screen, path, prepared=None: shown.append((path.parent.name, path.name, clock[0])) or True)
    monkeypatch.setattr(slideshow, 'display_message', lambda screen, text: waiting.append(clock[0]))
    monkeypatch.setattr(slideshow, 'handle_events', lambda: clock[0] < 2200)
    with TestClient(create_app(settings)) as browser:
        def wait(milliseconds):
            clock[0] += 100
            if clock[0] == 100:
                browser.post('/folder', data={'folder': selection})
                other = app.cache / 'summer/new.jpg'
                other.touch()
                queue.put(other)
                chosen = app.cache / selection / 'new.jpg'
                if selection != 'empty':
                    chosen.touch()
                    queue.put(chosen)
            assert clock[0] < 2500
        monkeypatch.setattr(slideshow.pygame.time, 'wait', wait)
        slideshow.show_slideshow(settings, new_photos=queue)
    assert shown[0] == ('summer', 'a.jpg', 0)
    if selection == 'kids':
        assert shown[1] == ('kids', 'new.jpg', 1000)
        assert all(folder == 'kids' for folder, _, _ in shown[1:])
    else:
        assert len(shown) == 1
        assert waiting[0] == 1000


def test_multiple_arrivals_keep_fifo_priority_and_skip_duplicates(app, monkeypatch):
    from client.settings import RuntimeSettings
    slideshow = app.slideshow
    directory = app.cache / 'kids'
    directory.mkdir(parents=True)
    for name in ['a.jpg', 'b.jpg', 'c.jpg']:
        (directory / name).touch()
    queue = SimpleQueue()
    shown = []
    clock = [0]
    def wait(milliseconds):
        clock[0] += milliseconds
        if clock[0] == 10:
            for name in ['z.jpg', 'z.jpg', 'a.jpg', 'aa.jpg']:
                path = directory / name
                path.touch()
                queue.put(path)
        assert clock[0] < 6000
    monkeypatch.setattr(slideshow.pygame.time, 'get_ticks', lambda: clock[0])
    monkeypatch.setattr(slideshow.pygame.time, 'wait', wait)
    monkeypatch.setattr(slideshow, 'display_photo', lambda screen, path, prepared=None: shown.append(path.name) or True)
    monkeypatch.setattr(slideshow, 'handle_events', lambda: len(shown) < 5)
    slideshow.show_slideshow(RuntimeSettings(1), new_photos=queue)
    assert shown == ['a.jpg', 'z.jpg', 'aa.jpg', 'b.jpg', 'c.jpg']
