"""Cloud dates drive offline ordering and album details, independent of local mtimes."""

import json
import os
from threading import Event, Thread

from fastapi.testclient import TestClient
import pytest

from client.cache import CacheIndex, MANIFEST, cached_photos
from client.control.app import create_app
from client.settings import RuntimeSettings


def seed(cache):
    for folder in ("kids", "summer", "empty", "All"):
        (cache / folder).mkdir(parents=True)
    for name in ("kids/a.jpg", "kids/z.jpg", "summer/b.png", "summer/unknown.jpg"):
        (cache / name).touch()
    # Neither a local repair nor a recent edit makes an old upload new.
    os.utime(cache / "kids/a.jpg", (2_000_000_000, 2_000_000_000))
    catalog = {
        "photos": {
            "old": {"path": "kids/a.jpg", "created": "2024-01-01T00:00:00Z",
                    "modified": "2026-09-12T23:00:00-05:00"},
            "new": {"path": "kids/z.jpg", "created": "2026-09-12T00:00:00Z"},
            "middle": {"path": "summer/b.png", "created": "2025-01-01T00:00:00Z"},
            "absent": {"path": "summer/not-cached.jpg", "created": "2027-01-01T00:00:00Z"},
        },
        "folder_metadata": {
            "kids": {"modified": "2025-01-01T00:00:00Z"},
            "empty": {"created": "2026-08-01T00:00:00Z"},
        },
    }
    (cache / MANIFEST).write_text(json.dumps(catalog))
    (cache / "loose.jpg").touch()
    (cache / "kids/notes.txt").touch()
    (cache / "kids/download.part").touch()
    (cache / "kids/nested").mkdir()
    (cache / "kids/nested/ignored.jpg").touch()
    (cache / "kids/link.jpg").symlink_to(cache / "kids/a.jpg")
    return catalog


def test_offline_order_and_details_use_cloud_dates_and_only_cached_album_photos(tmp_path):
    seed(tmp_path)
    expected = ["kids/z.jpg", "summer/b.png", "kids/a.jpg", "summer/unknown.jpg"]
    assert [p.relative_to(tmp_path).as_posix() for p in cached_photos(tmp_path)] == expected
    index = CacheIndex(tmp_path)
    assert index.photos() == cached_photos(tmp_path)
    assert index.months() == ["2026-09", "2025-01", "2024-01"]
    assert index.month_counts() == {"2026-09": 1, "2025-01": 1, "2024-01": 1}
    assert [p.name for p in index.photos(["2025-01", "2024-01"])] == ["b.png", "a.jpg"]
    assert index.month_for(tmp_path / "summer/unknown.jpg") is None
    details = index.folder_details()
    assert details[None].count == 4
    assert details["kids"].count == details["summer"].count == 2
    assert details["kids"].updated.isoformat() == "2026-09-13T04:00:00+00:00"
    assert details[None].updated == details["kids"].updated
    assert details["empty"].count == 0
    assert details["empty"].updated.date().isoformat() == "2026-08-01"
    assert details["All"].updated is None


@pytest.mark.parametrize("content", [None, "{broken", "[]", '{"photos": []}',
    '{"photos": {"a": null, "b": {"path": []}}}',
    '{"photos": {"a": {"path": "kids/a.jpg", "created": "invalid"}}}',
    '{"photos": {"a": {"path": "kids/a.jpg", "created": "2026-09-12"}}}',
    '{"folder_metadata": {"kids": []}}'])
def test_missing_older_or_corrupt_metadata_keeps_cache_playable(tmp_path, content):
    seed(tmp_path)
    if content is None:
        (tmp_path / MANIFEST).unlink()
    else:
        (tmp_path / MANIFEST).write_text(content)
    index = CacheIndex(tmp_path)
    assert [p.name for p in index.photos()] == ["a.jpg", "z.jpg", "b.png", "unknown.jpg"]
    assert index.folder_details()[None].count == 4
    assert index.folder_details()[None].updated is None


def test_equal_instants_have_stable_filename_order(tmp_path):
    catalog = seed(tmp_path)
    catalog["photos"]["old"]["created"] = "2026-09-12T01:00:00+01:00"
    (tmp_path / MANIFEST).write_text(json.dumps(catalog))
    assert [p.name for p in cached_photos(tmp_path)][:2] == ["a.jpg", "z.jpg"]


def test_readers_keep_previous_snapshot_during_slow_index_refresh(tmp_path, monkeypatch):
    seed(tmp_path)
    index = CacheIndex(tmp_path)
    before = index.photos()
    (tmp_path / "kids/new.jpg").touch()
    entered, release = Event(), Event()
    from client import cache as cache_module
    original = cache_module.cached_photos

    def slow_photos(*args, **kwargs):
        entered.set()
        assert release.wait(2)
        return original(*args, **kwargs)

    monkeypatch.setattr(cache_module, "cached_photos", slow_photos)
    thread = Thread(target=index.refresh, kwargs={"force": True})
    thread.start()
    try:
        assert entered.wait(2)
        assert index.photos() == before
    finally:
        release.set()
        thread.join(2)
    assert not thread.is_alive()
    assert tmp_path / "kids/new.jpg" in index.photos()


@pytest.mark.parametrize("selection,expected", [
    (None, ["z.jpg", "b.png", "a.jpg", "unknown.jpg", "z.jpg"]),
    ("kids", ["z.jpg", "a.jpg", "z.jpg"]),
])
def test_slideshow_plays_newest_first_in_all_and_selected_folder_across_cycles(
        app, monkeypatch, selection, expected):
    seed(app.cache)
    index = CacheIndex(app.cache)
    settings = RuntimeSettings(1, folders=index.folders)
    settings.set_folder(selection)
    slideshow = app.slideshow
    shown = []
    clock = [0.0]
    monkeypatch.setattr(slideshow.time, "monotonic", lambda: clock[0])

    def display(player, path, prepared=None):
        shown.append(path.name)
        if len(shown) >= len(expected):
            player.running = False
        return True

    def wait(player, milliseconds):
        clock[0] += milliseconds / 1000
        assert clock[0] < 6, "Slideshow failed to complete a cycle"

    monkeypatch.setattr(slideshow, "display_photo", display)
    app.FakeMPV.wait_hook = wait
    slideshow.show_slideshow(settings, index=index)
    assert shown == expected


def test_slideshow_combines_selected_months_across_folders(app, monkeypatch):
    seed(app.cache)
    index = CacheIndex(app.cache)
    settings = RuntimeSettings(1, folders=index.folders, months=index.months)
    settings.set_folder("kids")
    settings.set_months(["2025-01", "2024-01"])
    shown = []
    clock = [0.0]
    monkeypatch.setattr(app.slideshow.time, "monotonic", lambda: clock[0])

    def display(player, path, prepared=None):
        shown.append(path.relative_to(app.cache).as_posix())
        if len(shown) >= 3:
            player.running = False
        return True

    def wait(player, milliseconds):
        clock[0] += milliseconds / 1000
        assert clock[0] < 4

    monkeypatch.setattr(app.slideshow, "display_photo", display)
    app.FakeMPV.wait_hook = wait
    app.slideshow.show_slideshow(settings, index=index)

    assert shown == ["summer/b.png", "kids/a.jpg", "summer/b.png"]
    assert settings.playback_selection() == (
        "months", None, ("2025-01", "2024-01"))


def test_dropdown_details_refresh_without_changing_folder_values(tmp_path):
    catalog = seed(tmp_path)
    index = CacheIndex(tmp_path)
    settings = RuntimeSettings(5, folders=index.folders, months=index.months)
    with TestClient(create_app(settings, index=index)) as browser:
        page = browser.get("/").text
        assert 'value="2026-09">09-2026 — 1 picture</label>' in page
        assert 'value="2025-01">01-2025 — 1 picture</label>' in page
        assert '<option value="" selected>All — 4 pictures — updated 2026-09-13</option>' in page
        assert '<option value="empty">empty — 0 pictures — updated 2026-08-01</option>' in page
        assert '<option value="All">All — 0 pictures — updated unknown</option>' in page
        page = browser.post("/folder", data={"folder": "kids"}).text
        assert '<option value="kids" selected>kids — 2 pictures — updated 2026-09-13</option>' in page
        assert settings.selected_folder == "kids"
        (tmp_path / "kids/z.jpg").unlink()
        (tmp_path / 'fun & "things"').mkdir()
        catalog["photos"]["old"]["modified"] = "2026-09-15T00:00:00Z"
        (tmp_path / MANIFEST).write_text(json.dumps(catalog))
        index.refresh(force=True)
        page = browser.get("/").text
        assert 'kids — 1 picture — updated 2026-09-15</option>' in page
        assert 'All — 3 pictures — updated 2026-09-15</option>' in page
        assert '<option value="fun &amp; &quot;things&quot;">fun &amp; &quot;things&quot; — 0 pictures' in page
