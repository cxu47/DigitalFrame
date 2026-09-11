"""Practical cache workflows, using actual temporary files."""

from unittest.mock import Mock


def test_sync_publishes_complete_downloads_and_is_repeatable(app, monkeypatch):
    remote = [
        {"id": "one", "name": "family.jpg"},
        {"id": "duplicate", "name": "family.jpg"},
        {"id": "two", "name": "trip.png"},
    ]
    listing = Mock(return_value=remote)
    monkeypatch.setattr(app.sync, "list_photos", listing)
    downloads = []

    def download(file_id, destination):
        assert destination.suffix == ".part"
        assert not destination.with_suffix("").exists()
        destination.write_bytes(file_id.encode())
        assert destination not in app.slideshow.get_cached_photos()
        downloads.append(file_id)

    monkeypatch.setattr(app.sync, "download_photo", download)
    assert not app.cache.exists()
    app.sync.sync_photos()
    app.sync.sync_photos()

    listing.assert_called_with("test-folder")
    assert downloads == ["one", "two"]
    assert {p.name: p.read_bytes() for p in app.cache.iterdir()} == {
        "family.jpg": b"one", "trip.png": b"two",
    }


def test_failed_download_is_cleaned_up_other_photos_continue_and_retry_succeeds(app, monkeypatch):
    monkeypatch.setattr(app.sync, "list_photos", lambda folder: [
        {"id": "one", "name": "one.jpg"}, {"id": "two", "name": "two.jpg"},
    ])
    attempts = []

    def download(file_id, destination):
        attempts.append(file_id)
        destination.write_bytes(b"partial")
        if attempts == ["one"]:
            raise ConnectionError("Interrupted download")
        destination.write_bytes(b"complete")

    monkeypatch.setattr(app.sync, "download_photo", download)
    app.sync.sync_photos()
    assert {p.name for p in app.cache.iterdir()} == {"two.jpg"}

    app.sync.sync_photos()
    assert attempts == ["one", "two", "one"]
    assert {p.name: p.read_bytes() for p in app.cache.iterdir()} == {
        "one.jpg": b"complete", "two.jpg": b"complete",
    }


def test_listing_outage_preserves_cache_and_next_sync_recovers(app, monkeypatch):
    app.cache.mkdir()
    cached = app.cache / "existing.jpg"
    cached.write_bytes(b"cached photo")
    listing = Mock(side_effect=[ConnectionError("Offline"), [{"id": "new", "name": "new.jpg"}], []])
    download = Mock(side_effect=lambda file_id, path: path.write_bytes(b"new photo"))
    monkeypatch.setattr(app.sync, "list_photos", listing)
    monkeypatch.setattr(app.sync, "download_photo", download)

    app.sync.sync_photos()
    download.assert_not_called()
    assert cached.read_bytes() == b"cached photo"
    app.sync.sync_photos()
    app.sync.sync_photos()  # Current build retains cached files absent from Drive.
    assert {p.name: p.read_bytes() for p in app.cache.iterdir()} == {
        "existing.jpg": b"cached photo", "new.jpg": b"new photo",
    }
