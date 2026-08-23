from client import slideshow


def test_get_cached_photos_filters_and_sorts(tmp_path, monkeypatch):
    monkeypatch.setattr(slideshow, "CACHE_DIR", tmp_path)

    (tmp_path / "b.png").write_bytes(b"fake")
    (tmp_path / "a.jpg").write_bytes(b"fake")
    (tmp_path / "notes.txt").write_text("ignore me")
    (tmp_path / ".gitkeep").write_text("")

    photos = slideshow.get_cached_photos()

    assert [photo.name for photo in photos] == [
        "a.jpg",
        "b.png",
    ]


def test_get_cached_photos_empty(tmp_path, monkeypatch):
    monkeypatch.setattr(slideshow, "CACHE_DIR", tmp_path)

    photos = slideshow.get_cached_photos()

    assert photos == []
