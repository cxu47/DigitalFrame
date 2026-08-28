import logging

from client import sync


def test_sync_downloads_missing_photo(tmp_path, monkeypatch, caplog):
    monkeypatch.setattr(sync, "CACHE_DIR", tmp_path)
    monkeypatch.setattr(
        sync,
        "list_photos",
        lambda folder_id: [{"id": "drive-file-id", "name": "one.jpg"}],
    )

    download_calls = []

    def fake_download(file_id, destination):
        download_calls.append((file_id, destination))
        destination.write_bytes(b"fake image data")

    monkeypatch.setattr(sync, "download_photo", fake_download)

    with caplog.at_level(logging.INFO, logger=sync.__name__):
        sync.sync_photos()

    assert download_calls == [
        ("drive-file-id", tmp_path / "one.jpg.part")
    ]
    assert (tmp_path / "one.jpg").read_bytes() == b"fake image data"
    assert not (tmp_path / "one.jpg.part").exists()
    assert "Downloading one.jpg" in caplog.messages
    assert "Downloaded one.jpg" in caplog.messages
    assert (
        "Photo sync completed: 1 remote, 1 downloaded, 0 cached, 0 failed"
        in caplog.messages
    )


def test_sync_skips_cached_photo(tmp_path, monkeypatch, caplog):
    monkeypatch.setattr(sync, "CACHE_DIR", tmp_path)
    monkeypatch.setattr(
        sync,
        "list_photos",
        lambda folder_id: [{"id": "drive-file-id", "name": "one.jpg"}],
    )

    cached_photo = tmp_path / "one.jpg"
    cached_photo.write_bytes(b"already cached")
    download_calls = []
    monkeypatch.setattr(
        sync,
        "download_photo",
        lambda file_id, destination: download_calls.append(
            (file_id, destination)
        ),
    )

    with caplog.at_level(logging.DEBUG, logger=sync.__name__):
        sync.sync_photos()

    assert download_calls == []
    assert cached_photo.read_bytes() == b"already cached"
    assert "Already cached: one.jpg" in caplog.messages
    assert (
        "Photo sync completed: 1 remote, 0 downloaded, 1 cached, 0 failed"
        in caplog.messages
    )


def test_sync_keeps_cache_when_listing_fails(
    tmp_path,
    monkeypatch,
    caplog,
):
    monkeypatch.setattr(sync, "CACHE_DIR", tmp_path)

    cached_photo = tmp_path / "cached.jpg"
    cached_photo.write_bytes(b"existing photo")

    def fake_list_photos(folder_id):
        raise ConnectionError("Google Drive unavailable")

    monkeypatch.setattr(sync, "list_photos", fake_list_photos)

    with caplog.at_level(logging.ERROR, logger=sync.__name__):
        sync.sync_photos()

    assert cached_photo.read_bytes() == b"existing photo"
    error_record = next(
        record
        for record in caplog.records
        if "failed while listing" in record.getMessage()
    )
    assert error_record.exc_info is not None


def test_sync_removes_partial_file_when_download_fails(
    tmp_path,
    monkeypatch,
    caplog,
):
    monkeypatch.setattr(sync, "CACHE_DIR", tmp_path)
    monkeypatch.setattr(
        sync,
        "list_photos",
        lambda folder_id: [{"id": "drive-file-id", "name": "one.jpg"}],
    )

    def fake_download(file_id, destination):
        destination.write_bytes(b"partial")
        raise OSError("download interrupted")

    monkeypatch.setattr(sync, "download_photo", fake_download)

    with caplog.at_level(logging.INFO, logger=sync.__name__):
        sync.sync_photos()

    assert not (tmp_path / "one.jpg").exists()
    assert not (tmp_path / "one.jpg.part").exists()
    error_record = next(
        record
        for record in caplog.records
        if record.getMessage() == "Failed to download one.jpg"
    )
    assert error_record.levelno == logging.ERROR
    assert error_record.exc_info is not None
    assert (
        "Photo sync completed: 1 remote, 0 downloaded, 0 cached, 1 failed"
        in caplog.messages
    )
