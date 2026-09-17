"""Exercise slideshow policy against an in-memory mpv test double."""

from queue import SimpleQueue
from threading import Event

from PIL import Image
import pytest


def make_photo(path, color="red", size=(20, 10), *, image_format=None):
    path.parent.mkdir(parents=True, exist_ok=True)
    with Image.new("RGB", size, color) as image:
        image.save(path, format=image_format)


def clocked(app, monkeypatch, stop_when):
    clock = [0.0]
    monkeypatch.setattr(app.slideshow.time, "monotonic", lambda: clock[0])

    def wait(player, milliseconds):
        clock[0] += milliseconds / 1000
        if stop_when(player, clock[0]):
            player.running = False
        assert clock[0] < 20

    app.FakeMPV.wait_hook = wait
    return clock


def test_cache_selection_never_exposes_iphone_or_partial_files_to_mpv(app):
    album = app.cache / "kids"
    album.mkdir(parents=True)
    for name in ("a.jpg", "b.PNG", "c.webp", "phone.heic", "phone.heif", "photo.jpg.part", "notes.txt"):
        (album / name).touch()
    (app.cache / "loose.jpg").touch()

    assert [p.name for p in app.slideshow.get_cached_photos()] == ["a.jpg", "b.PNG", "c.webp"]


@pytest.mark.parametrize("suffix,image_format", [("jpg", None), ("png", None), ("webp", None)])
def test_display_photo_delegates_supported_formats_to_mpv(app, tmp_path, suffix, image_format):
    photo = tmp_path / f"photo.{suffix}"
    make_photo(photo, image_format=image_format)
    player = app.FakeMPV()

    assert app.slideshow.display_photo(player, photo)
    assert player.loaded == [photo]


def test_missing_and_corrupt_images_are_skipped(app, tmp_path):
    player = app.FakeMPV()
    corrupt = tmp_path / "corrupt.jpg"
    corrupt.write_bytes(b"not a photo")
    assert not app.slideshow.display_photo(player, tmp_path / "missing.jpg")
    assert not app.slideshow.display_photo(player, corrupt)


def test_slideshow_waits_then_cycles_and_closes_player(app, monkeypatch):
    shown = []
    waits = [0]
    clock = [0.0]
    monkeypatch.setattr(app.slideshow.time, "monotonic", lambda: clock[0])
    original = app.slideshow.display_photo

    def display(player, path, prepared=None):
        success = original(player, path, prepared)
        if success:
            shown.append(path.name)
        return success

    def wait(player, milliseconds):
        waits[0] += 1
        clock[0] += milliseconds / 1000
        if waits[0] == 1:
            make_photo(app.cache / "kids/a.png")
            make_photo(app.cache / "kids/b.png")
        if len(shown) == 3:
            player.running = False
        assert waits[0] < 500

    app.FakeMPV.wait_hook = wait
    monkeypatch.setattr(app.slideshow, "display_photo", display)
    app.slideshow.show_slideshow()

    assert shown == ["a.png", "b.png", "a.png"]
    assert app.FakeMPV.instances[-1].closed
    assert app.FakeMPV.instances[-1].stops == 1


def test_restart_request_stops_and_closes_slideshow(app):
    stop = Event()
    stop.set()

    app.slideshow.show_slideshow(stop_event=stop)

    assert app.FakeMPV.instances[-1].closed


@pytest.mark.parametrize("initial,updated", [(5, 10), (5, 1)])
def test_setting_update_applies_at_next_photo(app, monkeypatch, initial, updated):
    from client.settings import RuntimeSettings

    for name in ("a.jpg", "b.jpg", "c.jpg"):
        make_photo(app.cache / "kids" / name)
    settings = RuntimeSettings(initial)
    shown = []
    changed = [False]
    original = app.slideshow.display_photo
    clock = clocked(app, monkeypatch, lambda player, now: len(shown) >= 3)

    def display(player, path, prepared=None):
        success = original(player, path, prepared)
        if success:
            shown.append((path.name, clock[0]))
        return success

    def wait(player, milliseconds):
        clock[0] += milliseconds / 1000
        if not changed[0]:
            settings.set_display_seconds(updated)
            changed[0] = True
        if len(shown) >= 3:
            player.running = False

    app.FakeMPV.wait_hook = wait
    monkeypatch.setattr(app.slideshow, "display_photo", display)
    app.slideshow.show_slideshow(settings)

    assert [name for name, _ in shown] == ["a.jpg", "b.jpg", "c.jpg"]
    assert [when for _, when in shown] == pytest.approx(
        [0, initial, initial + updated], abs=0.005,
    )


def test_sync_arrivals_play_fifo_then_rotation_resumes(app, monkeypatch):
    from client.settings import RuntimeSettings

    for name in ("a.jpg", "b.jpg", "c.jpg"):
        make_photo(app.cache / "kids" / name)
    queue = SimpleQueue()
    shown = []
    original = app.slideshow.display_photo
    clock = clocked(app, monkeypatch, lambda player, now: len(shown) >= 5)

    def display(player, path, prepared=None):
        success = original(player, path, prepared)
        if success:
            shown.append(path.name)
        return success

    added = [False]

    def wait(player, milliseconds):
        clock[0] += milliseconds / 1000
        if not added[0]:
            for name in ("z.jpg", "z.jpg", "aa.jpg"):
                path = app.cache / "kids" / name
                make_photo(path, "blue")
                queue.put(path)
            added[0] = True
        if len(shown) >= 5:
            player.running = False

    app.FakeMPV.wait_hook = wait
    monkeypatch.setattr(app.slideshow, "display_photo", display)
    app.slideshow.show_slideshow(RuntimeSettings(1), new_photos=queue)

    assert shown == ["a.jpg", "z.jpg", "aa.jpg", "b.jpg", "c.jpg"]


def test_folder_change_applies_only_at_photo_boundary(app, monkeypatch):
    from client.settings import RuntimeSettings

    for folder, names in (("summer", ("a.jpg", "b.jpg")), ("kids", ("c.jpg",))):
        for name in names:
            make_photo(app.cache / folder / name)
    settings = RuntimeSettings(1, folders=app.slideshow.get_cached_folders)
    settings.set_folder("summer")
    shown = []
    original = app.slideshow.display_photo
    clock = clocked(app, monkeypatch, lambda player, now: len(shown) >= 2)

    def display(player, path, prepared=None):
        success = original(player, path, prepared)
        if success:
            shown.append((path.parent.name, clock[0]))
        return success

    changed = [False]

    def wait(player, milliseconds):
        clock[0] += milliseconds / 1000
        if not changed[0]:
            settings.set_folder("kids")
            changed[0] = True
        if len(shown) >= 2:
            player.running = False

    app.FakeMPV.wait_hook = wait
    monkeypatch.setattr(app.slideshow, "display_photo", display)
    app.slideshow.show_slideshow(settings)

    assert shown[0] == ("summer", 0)
    assert shown[1][0] == "kids"
    assert shown[1][1] == pytest.approx(1)
