"""Exercise album reconciliation with real cache files and offline Drive metadata."""

from queue import SimpleQueue
from unittest.mock import Mock


def photo(file_id, name=None, version="v1"):
    return {"id": file_id, "name": name or f"{file_id}.jpg", "md5Checksum": version}


def album(folder_id, photos=(), name=None):
    return {"id": folder_id, "name": name or folder_id, "photos": list(photos)}


def setup_sync(app, monkeypatch, remote):
    listing = Mock(return_value=remote)
    download = Mock(side_effect=lambda file_id, destination: destination.write_bytes(file_id.encode()))
    monkeypatch.setattr(app.sync, "list_albums", listing)
    monkeypatch.setattr(app.sync, "download_photo", download)
    return listing, download


def cached(app):
    return {str(path.relative_to(app.cache)): path.read_bytes()
            for path in app.slideshow.get_cached_photos()}


def test_sync_mirrors_albums_and_empty_folders_without_repeated_downloads(app, monkeypatch):
    remote = [album("kids", [photo("one", "family.jpg")]),
              album("summer", [photo("two", "family.jpg")]), album("empty")]
    listing, download = setup_sync(app, monkeypatch, remote)
    queue = SimpleQueue()
    app.sync.sync_photos(queue)
    assert cached(app) == {"kids/family.jpg": b"one", "summer/family.jpg": b"two"}
    assert app.slideshow.get_cached_folders() == ["empty", "kids", "summer"]
    assert queue.get_nowait() == app.cache / "kids/family.jpg"
    assert queue.get_nowait() == app.cache / "summer/family.jpg"
    app.sync.sync_photos(queue)
    assert download.call_count == 2
    assert queue.empty()
    listing.assert_called_with("test-folder")
    (app.cache / "kids/family.jpg").unlink()
    app.sync.sync_photos()
    assert download.call_count == 3  # Repair a missing local file even with the same hash.


def test_duplicate_and_unsafe_names_stay_distinct_and_inside_cache(app, monkeypatch):
    remote = [album("a", [photo("one", "../photo.jpg"), photo("two", "../photo.jpg")], "../kids"),
              album("b", [photo("three")], "../kids")]
    _, download = setup_sync(app, monkeypatch, remote)
    app.sync.sync_photos()
    files = app.slideshow.get_cached_photos()
    assert len(files) == 3
    assert {p.read_bytes() for p in files} == {b"one", b"two", b"three"}
    assert all(p.parent.parent == app.cache for p in files)
    assert len(app.slideshow.get_cached_folders()) == 2
    app.sync.sync_photos()
    assert download.call_count == 3


def test_renames_moves_edits_deletions_and_folder_swaps(app, monkeypatch):
    listing, download = setup_sync(app, monkeypatch, [
        album("a", [photo("one"), photo("deleted")], "kids"),
        album("b", [photo("two")], "summer"), album("empty"),
    ])
    app.sync.sync_photos()
    download.reset_mock()
    listing.return_value = [album("a", [photo("two", "renamed.jpg")], "summer"),
                            album("b", [photo("one")], "kids")]
    app.sync.sync_photos()
    assert cached(app) == {"summer/renamed.jpg": b"two", "kids/one.jpg": b"one"}
    assert not (app.cache / "empty").exists()
    download.assert_not_called()
    listing.return_value = [album("b", [photo("one", version="v2")], "fun things")]
    download.side_effect = lambda file_id, path: path.write_bytes(b"edited")
    app.sync.sync_photos()
    assert cached(app) == {"fun things/one.jpg": b"edited"}
    assert app.slideshow.get_cached_folders() == ["fun things"]
    download.assert_called_once()
    listing.return_value = []
    app.sync.sync_photos()
    assert cached(app) == {}
    assert app.slideshow.get_cached_folders() == []


def test_swapping_photo_names_reuses_correct_content(app, monkeypatch):
    listing, download = setup_sync(app, monkeypatch, [album("kids", [photo("a"), photo("b")])])
    app.sync.sync_photos()
    listing.return_value = [album("kids", [photo("a", "b.jpg"), photo("b", "a.jpg")])]
    app.sync.sync_photos()
    assert cached(app) == {"kids/a.jpg": b"b", "kids/b.jpg": b"a"}
    assert download.call_count == 2


def test_listing_outage_preserves_entire_cache(app, monkeypatch):
    listing, download = setup_sync(app, monkeypatch, [album("kids", [photo("one")])])
    app.sync.sync_photos()
    manifest = (app.cache / app.sync.MANIFEST).read_bytes()
    listing.side_effect = ConnectionError("Offline halfway through folder listing")
    app.sync.sync_photos()
    assert cached(app) == {"kids/one.jpg": b"one"}
    assert (app.cache / app.sync.MANIFEST).read_bytes() == manifest
    assert download.call_count == 1


def test_partial_downloads_retry_and_publish_immediately(app, monkeypatch):
    _, download = setup_sync(app, monkeypatch, [album("kids", [photo("one"), photo("two")])])
    queue = SimpleQueue()
    attempts = []

    def transfer(file_id, destination):
        attempts.append(file_id)
        destination.write_bytes(b"partial")
        assert destination.suffix == ".part"
        assert destination not in app.slideshow.get_cached_photos()
        if attempts == ["one"]:
            raise ConnectionError("Interrupted")
        destination.write_bytes(b"complete")

    download.side_effect = transfer
    app.sync.sync_photos(queue)
    assert cached(app) == {"kids/two.jpg": b"complete"}
    assert queue.get_nowait() == app.cache / "kids/two.jpg"
    assert queue.empty()
    assert not list(app.cache.glob("*/*.part"))
    app.sync.sync_photos(queue)
    assert attempts == ["one", "two", "one"]
    assert queue.get_nowait() == app.cache / "kids/one.jpg"
    assert queue.empty()


def test_failed_update_keeps_old_photo_and_retries_same_remote_hash(app, monkeypatch):
    listing, download = setup_sync(app, monkeypatch, [album("kids", [photo("one")])])
    app.sync.sync_photos()
    listing.return_value = [album("kids", [photo("one", version="v2")])]
    download.side_effect = ConnectionError("Offline")
    app.sync.sync_photos()
    assert cached(app) == {"kids/one.jpg": b"one"}
    download.side_effect = lambda file_id, path: path.write_bytes(b"edited")
    app.sync.sync_photos()
    assert cached(app) == {"kids/one.jpg": b"edited"}


def test_each_completed_file_is_queued_before_next_download(app, monkeypatch):
    _, download = setup_sync(app, monkeypatch, [album("kids", [photo("one"), photo("two")])])
    queue = SimpleQueue()

    def transfer(file_id, path):
        if file_id == "two":
            published = queue.get_nowait()
            assert published.read_bytes() == b"complete"
            assert published == app.cache / "kids/one.jpg"
        assert queue.empty()
        path.write_bytes(b"complete")
        assert queue.empty()

    download.side_effect = transfer
    app.sync.sync_photos(queue)
    assert queue.get_nowait() == app.cache / "kids/two.jpg"
    app.sync.sync_photos(queue)
    assert queue.empty()
