"""Verify independent mpv OSD state and expiration."""

import pytest

from client import overlay


@pytest.fixture
def clock(monkeypatch):
    value = [100.0]
    monkeypatch.setattr(overlay.time, "monotonic", lambda: value[0])
    return value


def test_url_overlay_expires_without_touching_the_photo(app, clock):
    player = app.FakeMPV()
    banner = overlay.SlideshowOverlay(player, "http://192.168.1.42:8000", 30)
    assert player.overlays[1] == ("Control: http://192.168.1.42:8000", "white", "top")
    clock[0] = 129.99
    banner.update()
    assert 1 in player.overlays
    clock[0] = 130
    banner.update()
    assert 1 not in player.overlays
    assert player.loaded == []


@pytest.mark.parametrize("url,seconds", [(None, 30), ("http://frame:8000", 0)])
def test_disabled_or_missing_url_has_no_overlay(app, clock, url, seconds):
    player = app.FakeMPV()
    overlay.SlideshowOverlay(player, url, seconds)
    assert 1 not in player.overlays


def test_setting_replaces_url_and_restarts_expiration(app, clock):
    player = app.FakeMPV()
    banner = overlay.SlideshowOverlay(player, "http://frame:8000", 30)
    clock[0] = 110
    banner.show_message("Seconds per photo: 5", 15)
    assert player.overlays[1][0] == "Seconds per photo: 5"
    assert banner.deadline == 125
    clock[0] = 120
    banner.show_message("Photo folder: kids", 15)
    assert banner.deadline == 135
    clock[0] = 135
    banner.update()
    assert 1 not in player.overlays


def test_wait_is_shortened_to_banner_deadline(app, clock):
    player = app.FakeMPV()
    banner = overlay.SlideshowOverlay(player, "http://frame:8000", 30)
    clock[0] = 129.75

    def wait(instance, milliseconds):
        assert milliseconds == 250
        clock[0] += milliseconds / 1000

    app.FakeMPV.wait_hook = wait
    banner.wait(5000)
    assert 1 not in player.overlays


def test_network_warning_is_red_persistent_and_temporarily_suppresses_notice(app, clock):
    player = app.FakeMPV()
    banner = overlay.SlideshowOverlay(player, None, 0)
    banner.set_network_message("Internet unavailable\nControl: http://10.42.0.1:8000")
    assert player.overlays[1][1] == "red"
    clock[0] += 36000
    banner.update()
    assert "Internet unavailable" in player.overlays[1][0]
    banner.show_message("Photo folder: kids", 15)
    assert "Internet unavailable" in player.overlays[1][0]
    clock[0] += 1
    banner.set_network_message(None)
    assert player.overlays[1] == ("Photo folder: kids", "white", "top")
    clock[0] += 14
    banner.update()
    assert 1 not in player.overlays


def test_waiting_message_and_banner_use_separate_overlay_channels(app, clock):
    player = app.FakeMPV()
    from client.slideshow import display_message

    display_message(player, "No readable photos available. Waiting for photos.")
    banner = overlay.SlideshowOverlay(player, "http://frame:8000", 30)
    assert player.overlays[2][2] == "center"
    assert player.overlays[1][2] == "top"
    clock[0] = 130
    banner.update()
    assert 1 not in player.overlays and 2 in player.overlays
