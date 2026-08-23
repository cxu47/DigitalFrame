from client import sync


def test_download_photo(tmp_path, monkeypatch):
    monkeypatch.setattr(sync, "CACHE_DIR", tmp_path)

    class FakeResponse:
        content = b"fake image data"

        def raise_for_status(self):
            pass

    def fake_get(url, **kwargs):
        return FakeResponse()

    monkeypatch.setattr(sync.httpx, "get", fake_get)

    sync.download_photo("test.jpg")

    assert (tmp_path / "test.jpg").exists()
    assert (tmp_path / "test.jpg").read_bytes() == b"fake image data"


def test_sync_downloads_missing_photo(tmp_path, monkeypatch):
    monkeypatch.setattr(sync, "CACHE_DIR", tmp_path)
    monkeypatch.setattr(sync, "get_photo_names", lambda: ["one.jpg"])

    downloaded = []

    def fake_download(filename):
        downloaded.append(filename)
        (tmp_path / filename).write_bytes(b"fake")

    monkeypatch.setattr(sync, "download_photo", fake_download)

    sync.sync_photos()

    assert downloaded == ["one.jpg"]
    assert (tmp_path / "one.jpg").exists()


def test_sync_skips_cached_photo(tmp_path, monkeypatch):
    monkeypatch.setattr(sync, "CACHE_DIR", tmp_path)
    monkeypatch.setattr(sync, "get_photo_names", lambda: ["one.jpg"])

    (tmp_path / "one.jpg").write_bytes(b"already cached")

    downloaded = []

    monkeypatch.setattr(
        sync,
        "download_photo",
        lambda filename: downloaded.append(filename),
    )

    sync.sync_photos()

    assert downloaded == []

def test_sync_keeps_cache_when_server_unavailable(tmp_path, monkeypatch):
    monkeypatch.setattr(sync, "CACHE_DIR", tmp_path)

    cached_photo = tmp_path / "cached.jpg"
    cached_photo.write_bytes(b"existing photo")

    def fake_get_photo_names():
        raise sync.httpx.ConnectError("server unavailable")

    monkeypatch.setattr(sync, "get_photo_names", fake_get_photo_names)

    sync.sync_photos()

    assert cached_photo.exists()
    assert cached_photo.read_bytes() == b"existing photo"


def test_download_photo_uses_temp_file(tmp_path, monkeypatch):
    monkeypatch.setattr(sync, "CACHE_DIR", tmp_path)

    class FakeResponse:
        content = b"fake image data"

        def raise_for_status(self):
            pass

    monkeypatch.setattr(
        sync.httpx,
        "get",
        lambda url, **kwargs: FakeResponse(),
    )

    sync.download_photo("test.jpg")

    assert (tmp_path / "test.jpg").exists()
    assert (tmp_path / "test.jpg").read_bytes() == b"fake image data"
    assert not (tmp_path / "test.jpg.part").exists()
