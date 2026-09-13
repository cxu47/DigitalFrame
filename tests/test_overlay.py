"""Check actual banner pixels and expiration with a fake clock and dummy SDL."""

import pytest

pytestmark = pytest.mark.usefixtures("immediate_loader")

from client import overlay


@pytest.fixture
def clock(monkeypatch):
    seconds = [100.0]
    monkeypatch.setattr(overlay.time, "monotonic", lambda: seconds[0])
    return seconds


def pixels(screen):
    return overlay.pygame.image.tobytes(screen, "RGB")


def test_url_is_at_top_left_and_restores_photo_at_deadline(screen, clock):
    screen.fill("red")
    original = pixels(screen)
    banner = overlay.SlideshowOverlay(screen, "http://192.168.1.42:8000", 30)
    banner.new_frame()
    assert pixels(screen) != original
    assert banner.rect.topleft == (8, 8)
    assert banner.rect.right <= screen.get_width()
    assert screen.get_at((8, 8))[:3] == (0, 0, 0)
    assert screen.get_at((0, 0))[:3] == (255, 0, 0)
    clock[0] = 129.99
    banner.update()
    assert pixels(screen) != original
    clock[0] = 130
    banner.update()
    assert pixels(screen) == original
    assert banner.background is None


def test_expiration_restores_latest_photo_and_does_not_reset_for_each_photo(screen, clock):
    screen.fill("red")
    banner = overlay.SlideshowOverlay(screen, "http://192.168.1.42:8000", 30)
    banner.new_frame()
    clock[0] = 120
    screen.fill("blue")
    latest = pixels(screen)
    banner.new_frame()
    assert pixels(screen) != latest
    clock[0] = 130
    banner.update()
    assert pixels(screen) == latest
    screen.fill("green")
    later = pixels(screen)
    banner.new_frame()
    assert pixels(screen) == later


@pytest.mark.parametrize("url,seconds", [(None, 30), ("http://192.168.1.42:8000", 0)])
def test_missing_address_or_disabled_overlay_leaves_pixels_unchanged(screen, clock, url, seconds):
    screen.fill("red")
    original = pixels(screen)
    banner = overlay.SlideshowOverlay(screen, url, seconds)
    banner.new_frame()
    banner.update()
    assert pixels(screen) == original


def test_wait_is_shortened_to_remove_banner_on_time(screen, clock, monkeypatch):
    screen.fill("red")
    original = pixels(screen)
    banner = overlay.SlideshowOverlay(screen, "http://192.168.1.42:8000", 30)
    banner.new_frame()
    waits = []

    def wait(milliseconds):
        waits.append(milliseconds)
        clock[0] += milliseconds / 1000

    monkeypatch.setattr(overlay.pygame.time, "wait", wait)
    banner.wait(60000)
    assert waits == [30000]
    assert pixels(screen) == original


def test_setting_message_replaces_url_and_restores_all_old_pixels(screen, clock):
    screen.fill("red")
    original = pixels(screen)
    banner = overlay.SlideshowOverlay(screen, "http://192.168.1.42:8000", 30)
    banner.new_frame()
    old_rect = banner.rect.copy()
    clock[0] = 105
    banner.show_message("5 sec", 15)
    assert banner.rect.topleft == old_rect.topleft
    assert banner.rect.width < old_rect.width
    assert screen.get_at((old_rect.right - 1, old_rect.top))[:3] == (255, 0, 0)
    clock[0] = 119.99
    banner.update()
    assert pixels(screen) != original
    clock[0] = 120
    banner.update()
    assert pixels(screen) == original


def test_new_setting_restarts_timer_and_restores_the_latest_photo(screen, clock):
    banner = overlay.SlideshowOverlay(screen, None, 0)
    screen.fill("red")
    banner.show_message("Seconds per photo: 5", 15)
    clock[0] = 110
    screen.fill("blue")
    latest = pixels(screen)
    banner.new_frame()
    banner.show_message("Seconds per photo: 10", 15)
    clock[0] = 115
    banner.update()
    assert pixels(screen) != latest
    clock[0] = 125
    banner.update()
    assert pixels(screen) == latest


@pytest.mark.parametrize("empty_cache", [False, True])
@pytest.mark.parametrize("url_seconds", [0, 30])
def test_form_updates_show_for_15_seconds_using_existing_overlay(
    app, clock, monkeypatch, empty_cache, url_seconds,
):
    from fastapi.testclient import TestClient
    from client.control.app import create_app
    from client.settings import RuntimeSettings

    slideshow = app.slideshow
    settings = RuntimeSettings(60)
    messages = []
    observed = []
    painted = []
    original_show = overlay.SlideshowOverlay.show_message

    def show_message(self, text, seconds):
        messages.append((clock[0], text, seconds))
        original_show(self, text, seconds)

    monkeypatch.setattr(overlay.SlideshowOverlay, "show_message", show_message)
    photo = app.cache / "kids" / "a.jpg"
    photo.parent.mkdir(parents=True)
    photo.touch()
    monkeypatch.setattr(slideshow, "get_cached_photos", lambda: [] if empty_cache else [photo])
    monkeypatch.setattr(slideshow.pygame.time, "get_ticks", lambda: int(clock[0] * 1000))
    monkeypatch.setattr(slideshow, "handle_events", lambda: clock[0] < 136)
    monkeypatch.setattr(slideshow, "IDLE_SECONDS", 1)

    def draw(screen, *args):
        screen.fill("red")
        painted.append(clock[0])
        return True

    monkeypatch.setattr(slideshow, "display_photo", draw)
    monkeypatch.setattr(slideshow, "display_message", draw)

    with TestClient(create_app(settings)) as browser:
        def wait(milliseconds):
            screen = slideshow.pygame.display.get_surface()
            observed.append((clock[0], screen.get_at((8, 8))[:3]))
            clock[0] += milliseconds / 1000
            if clock[0] == 101:
                assert browser.post("/settings", data={"display_seconds": "5.0"}).status_code == 422
            if clock[0] in {102, 110, 120}:
                value = "5" if clock[0] == 102 else "10"
                assert browser.post("/settings", data={"display_seconds": value}).status_code == 200
            assert clock[0] < 140

        monkeypatch.setattr(slideshow.pygame.time, "wait", wait)
        slideshow.show_slideshow(settings, control_url="http://192.168.1.42:8000",
                                 url_display_seconds=url_seconds)

    assert messages == [
        (102, "Seconds per photo: 5", 15),
        (110, "Seconds per photo: 10", 15),
        (120, "Seconds per photo: 10", 15),
    ]
    assert (102, (0, 0, 0)) in observed
    assert (134, (0, 0, 0)) in observed
    assert (135, (255, 0, 0)) in observed
    if not empty_cache:
        assert painted == [100]  # Accepted updates did not interrupt the current photo.
    assert not slideshow.pygame.get_init()


@pytest.mark.parametrize("empty_cache", [False, True])
def test_slideshow_removes_banner_during_long_photo_or_waiting_screen(app, clock, monkeypatch, empty_cache):
    slideshow = app.slideshow
    observed = []
    painted = []
    from client.settings import RuntimeSettings

    photo = app.cache / "kids" / "a.jpg"
    photo.parent.mkdir(parents=True)
    photo.touch()
    monkeypatch.setattr(slideshow, "get_cached_photos", lambda: [] if empty_cache else [photo])
    monkeypatch.setattr(slideshow.pygame.time, "get_ticks", lambda: int(clock[0] * 1000))
    monkeypatch.setattr(slideshow, "handle_events", lambda: clock[0] < 131)
    monkeypatch.setattr(slideshow, "IDLE_SECONDS", 1)

    def draw(screen, *args):
        screen.fill("red")
        painted.append(clock[0])
        return True

    monkeypatch.setattr(slideshow, "display_photo", draw)
    monkeypatch.setattr(slideshow, "display_message", draw)

    def wait(milliseconds):
        screen = slideshow.pygame.display.get_surface()
        observed.append((clock[0], screen.get_at((8, 8))[:3]))
        clock[0] += milliseconds / 1000
        assert clock[0] < 135

    monkeypatch.setattr(slideshow.pygame.time, "wait", wait)
    slideshow.show_slideshow(RuntimeSettings(60), control_url="http://192.168.1.42:8000",
                             url_display_seconds=30)
    assert (100, (0, 0, 0)) in observed
    assert (130, (255, 0, 0)) in observed
    if not empty_cache:
        assert painted == [100]
    assert not slideshow.pygame.get_init()


@pytest.mark.parametrize("empty_cache", [False, True])
@pytest.mark.parametrize("url_seconds", [0, 30])
def test_folder_notifications_share_banner_and_report_automatic_fallback(
    app, clock, monkeypatch, empty_cache, url_seconds,
):
    from fastapi.testclient import TestClient
    from client.control.app import create_app
    from client.settings import RuntimeSettings

    slideshow = app.slideshow
    folders = ["kids", "summer"]
    settings = RuntimeSettings(60, folders=lambda: folders)
    photo = app.cache / "kids" / "a.jpg"
    photo.parent.mkdir(parents=True)
    photo.touch()
    messages = []
    painted = []
    observed = []
    original_show = overlay.SlideshowOverlay.show_message

    def show_message(self, text, seconds):
        messages.append((clock[0], text, seconds))
        original_show(self, text, seconds)

    def draw(screen, *args):
        screen.fill("red")
        painted.append(clock[0])
        return True

    monkeypatch.setattr(overlay.SlideshowOverlay, "show_message", show_message)
    monkeypatch.setattr(slideshow, "get_cached_photos", lambda: [] if empty_cache else [photo])
    monkeypatch.setattr(slideshow.pygame.time, "get_ticks", lambda: int(clock[0] * 1000))
    monkeypatch.setattr(slideshow, "handle_events", lambda: clock[0] < 146)
    monkeypatch.setattr(slideshow, "IDLE_SECONDS", 1)
    monkeypatch.setattr(slideshow, "display_photo", draw)
    monkeypatch.setattr(slideshow, "display_message", draw)

    with TestClient(create_app(settings)) as browser:
        def wait(milliseconds):
            screen = slideshow.pygame.display.get_surface()
            observed.append((clock[0], screen.get_at((8, 8))[:3]))
            clock[0] += milliseconds / 1000
            if clock[0] == 101:
                assert browser.post("/folder", data={"folder": "missing"}).status_code == 422
            if clock[0] in {102, 110}:
                assert browser.post("/folder", data={"folder": "kids"}).status_code == 200
            if clock[0] == 112:
                browser.post("/settings", data={"display_seconds": "50"})
                browser.post("/folder", data={"folder": "summer"})
            if clock[0] == 114:
                browser.post("/folder", data={"folder": "kids"})
                browser.post("/settings", data={"display_seconds": "60"})
            if clock[0] == 116:
                browser.post("/folder", data={"folder": ""})
            if clock[0] == 120:
                browser.post("/folder", data={"folder": "summer"})
            if clock[0] == 130:
                folders.remove("summer")
            assert clock[0] < 150

        monkeypatch.setattr(slideshow.pygame.time, "wait", wait)
        slideshow.show_slideshow(settings, control_url="http://192.168.1.42:8000",
                                 url_display_seconds=url_seconds)

    assert messages == [
        (102, "Photo folder: kids", 15),
        (110, "Photo folder: kids", 15),
        (112, "Photo folder: summer", 15),
        (114, "Seconds per photo: 60", 15),
        (116, "Photo folder: All", 15),
        (120, "Photo folder: summer", 15),
        (130, "Photo folder: All", 15),
    ]
    assert (144, (0, 0, 0)) in observed
    assert (145, (255, 0, 0)) in observed
    if not empty_cache:
        assert painted == [100]  # Notifications leave the current photo and interval intact.
    assert settings.selected_folder is None
    assert not slideshow.pygame.get_init()


def test_network_warning_is_red_persistent_and_restores_latest_photo(screen, clock, monkeypatch):
    screen = overlay.pygame.display.set_mode((640, 120))
    screen.fill('blue')
    banner = overlay.SlideshowOverlay(screen, None, 0)
    banner.set_network_problem(True)
    assert banner.rect.topleft == (8, 8)
    label = overlay.pygame.image.tobytes(banner.label, 'RGB')
    assert any(label[i] > 100 and label[i + 1] == 0 and label[i + 2] == 0
               for i in range(0, len(label), 3))
    clock[0] = 10000
    before = pixels(screen)
    waits = []
    monkeypatch.setattr(overlay.pygame.time, 'wait', lambda milliseconds: waits.append(milliseconds))
    banner.wait(5000)
    assert waits == [5000]  # Persistent alerts must not shorten waits to zero.
    assert pixels(screen) == before
    banner.show_message('Photo folder: kids', 15)
    assert pixels(screen) == before  # Temporary messages cannot cover the red warning.
    screen.fill('green')
    latest = pixels(screen)
    banner.new_frame()
    assert pixels(screen) != latest
    clock[0] += 20
    banner.set_network_problem(False)
    assert pixels(screen) == latest


def test_recovery_restores_unexpired_setting_confirmation(screen, clock):
    screen.fill('blue')
    original = pixels(screen)
    banner = overlay.SlideshowOverlay(screen, None, 0)
    banner.set_network_problem(True)
    banner.show_message('Seconds per photo: 5', 15)
    clock[0] += 1
    banner.set_network_problem(False)
    assert banner.deadline == 115
    assert pixels(screen) != original
    clock[0] = 115
    banner.update()
    assert pixels(screen) == original


@pytest.mark.parametrize('empty_cache', [False, True])
@pytest.mark.parametrize('url_seconds', [0, 30])
def test_network_warning_persists_while_slideshow_continues_and_clears_on_recovery(
    app, clock, monkeypatch, empty_cache, url_seconds,
):
    import ssl
    from client.settings import RuntimeSettings
    from client.status import RuntimeStatus
    slideshow = app.slideshow
    status = RuntimeStatus()
    settings = RuntimeSettings(5, folders=lambda: ['kids'])
    photo = app.cache / 'kids/a.jpg'
    photo.parent.mkdir(parents=True)
    photo.touch()
    painted = []
    observed = []
    def draw(screen, *args):
        painted.append(clock[0])
        screen.fill('blue')
        return True
    def wait(milliseconds):
        screen = slideshow.pygame.display.get_surface()
        observed.append((clock[0], screen.get_at((8, 8))[:3]))
        clock[0] += milliseconds / 1000
        if clock[0] == 101:
            status.report_exception('Sync', ssl.SSLError('Wi-Fi disconnected'))
        if clock[0] == 105:
            settings.set_folder('kids')
        if clock[0] == 110:
            settings.set_display_seconds(5)
        if clock[0] == 135:
            status.clear('Sync')
        assert clock[0] < 142
    monkeypatch.setattr(slideshow, 'get_cached_photos', lambda: [] if empty_cache else [photo])
    monkeypatch.setattr(slideshow, 'display_photo', draw)
    monkeypatch.setattr(slideshow, 'display_message', draw)
    monkeypatch.setattr(slideshow, 'handle_events', lambda: clock[0] < 141)
    monkeypatch.setattr(slideshow, 'IDLE_SECONDS', 1)
    monkeypatch.setattr(slideshow.pygame.time, 'get_ticks', lambda: int(clock[0] * 1000))
    monkeypatch.setattr(slideshow.pygame.time, 'wait', wait)
    slideshow.show_slideshow(settings, status=status, control_url='http://192.168.1.42:8000',
                             url_display_seconds=url_seconds)
    assert (101, (0, 0, 0)) in observed
    assert (134, (0, 0, 0)) in observed  # Still visible beyond every transient timer.
    assert (135, (0, 0, 255)) in observed
    if not empty_cache:
        assert painted == list(range(100, 141, 5))
    assert not status.panel_snapshot()
