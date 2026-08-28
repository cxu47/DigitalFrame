import logging
from pathlib import Path

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


def test_show_first_photo_logs_empty_cache(
    tmp_path,
    monkeypatch,
    caplog,
):
    monkeypatch.setattr(slideshow, "CACHE_DIR", tmp_path)

    with caplog.at_level(logging.INFO, logger=slideshow.__name__):
        slideshow.show_first_photo()

    assert caplog.messages == ["No cached photos available"]


def test_display_photo_logs_unavailable_image(tmp_path, caplog):
    invalid_photo = tmp_path / "invalid.jpg"
    invalid_photo.write_bytes(b"not an image")

    with caplog.at_level(logging.WARNING, logger=slideshow.__name__):
        displayed = slideshow.display_photo(object(), invalid_photo)

    assert displayed is False
    warning_record = caplog.records[-1]
    assert warning_record.levelno == logging.WARNING
    assert warning_record.getMessage().startswith(
        "Skipping unavailable image invalid.jpg:"
    )
    assert warning_record.exc_info is None


def test_slideshow_logs_waiting_once_and_resuming(
    monkeypatch,
    caplog,
):
    photo = Path("photo.jpg")
    photo_batches = iter([[], [], [photo]])
    monkeypatch.setattr(
        slideshow,
        "get_cached_photos",
        lambda: next(photo_batches),
    )

    event_results = iter([True, True, False])
    monkeypatch.setattr(
        slideshow,
        "handle_events",
        lambda: next(event_results),
    )
    monkeypatch.setattr(slideshow, "display_message", lambda *args: None)
    monkeypatch.setattr(slideshow, "display_photo", lambda *args: True)
    monkeypatch.setattr(slideshow.pygame, "init", lambda: None)
    monkeypatch.setattr(slideshow.pygame, "quit", lambda: None)
    monkeypatch.setattr(
        slideshow.pygame.display,
        "set_mode",
        lambda size: object(),
    )
    monkeypatch.setattr(
        slideshow.pygame.display,
        "set_caption",
        lambda caption: None,
    )
    monkeypatch.setattr(slideshow.pygame.time, "wait", lambda delay: None)
    monkeypatch.setattr(slideshow.pygame.time, "get_ticks", lambda: 0)

    with caplog.at_level(logging.INFO, logger=slideshow.__name__):
        slideshow.show_slideshow()

    assert caplog.messages.count(
        "No cached photos available; waiting"
    ) == 1
    assert "Cached photos available; resuming slideshow" in caplog.messages
    assert caplog.messages[0] == "Slideshow started"
    assert caplog.messages[-1] == "Slideshow stopped"
