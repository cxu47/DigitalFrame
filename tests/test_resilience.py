"""Real thread boundaries, failed servers, and visible recovery messages."""

from threading import Event, get_ident
import time
from unittest.mock import Mock

import pytest
from PIL import Image


@pytest.mark.parametrize('change_folder', [False, True])
def test_next_image_loads_during_current_interval_and_folder_conflicts_are_lazy(app, monkeypatch, change_folder):
    from client.settings import RuntimeSettings
    slideshow = app.slideshow
    for folder, names in [('summer', ['a.png', 'b.png']), ('kids', ['c.png'])]:
        directory = app.cache / folder
        directory.mkdir(parents=True)
        for name in names:
            with Image.new('RGB', (20, 10), 'red') as source:
                source.save(directory / name)
    settings = RuntimeSettings(1, folders=slideshow.get_cached_folders)
    settings.set_folder('summer')
    second_started = Event()
    release_second = Event()
    prepare = slideshow.prepare_photo
    render = slideshow.display_photo
    clock = [0]
    shown = []
    worker_ids = []
    changed = [False]
    main_thread = get_ident()
    def decode(path, size):
        worker_ids.append(get_ident())
        if path.name == 'b.png':
            second_started.set()
            assert release_second.wait(2)
        return prepare(path, size)
    def display(screen, path, prepared=None):
        assert get_ident() == main_thread
        success = render(screen, path, prepared)
        if success:
            shown.append((path.name, clock[0]))
        return success
    def wait(milliseconds):
        clock[0] += milliseconds
        if shown and not changed[0]:
            assert second_started.wait(2), 'Next decode did not start while the first photo was visible'
            if change_folder:
                settings.set_folder('kids')
            release_second.set()
            changed[0] = True
        time.sleep(.001)  # Yield to the actual Pillow worker without advancing a real photo interval.
        assert clock[0] < 5000
    monkeypatch.setattr(slideshow, 'prepare_photo', decode)
    monkeypatch.setattr(slideshow, 'display_photo', display)
    monkeypatch.setattr(slideshow.pygame.time, 'get_ticks', lambda: clock[0])
    monkeypatch.setattr(slideshow.pygame.time, 'wait', wait)
    monkeypatch.setattr(slideshow, 'handle_events', lambda: len(shown) < 2)
    try:
        slideshow.show_slideshow(settings)
    finally:
        release_second.set()
    assert shown[0][0] == 'a.png'
    assert shown[1][0] == ('c.png' if change_folder else 'b.png')
    assert shown[1][1] - shown[0][1] >= 1000
    if not change_folder:
        assert shown[1][1] - shown[0][1] == 1000
    assert all(worker != main_thread for worker in worker_ids)


def test_single_photo_is_preloaded_for_next_cycle(app, monkeypatch):
    slideshow = app.slideshow
    directory = app.cache / 'kids'
    directory.mkdir(parents=True)
    with Image.new('RGB', (20, 10), 'red') as source:
        source.save(directory / 'a.png')
    prepare = slideshow.prepare_photo
    render = slideshow.display_photo
    second_decode = Event()
    calls = []
    shown = []
    clock = [0]
    def decode(path, size):
        result = prepare(path, size)
        calls.append(path)
        if len(calls) == 2:
            second_decode.set()
        return result
    def display(screen, path, prepared=None):
        shown.append(clock[0])
        return render(screen, path, prepared)
    def wait(milliseconds):
        if shown:
            assert second_decode.wait(2), 'Cycle wrap was not preloaded during the display interval'
        clock[0] += milliseconds
        time.sleep(.001)
        assert clock[0] < 3000
    monkeypatch.setattr(slideshow, 'prepare_photo', decode)
    monkeypatch.setattr(slideshow, 'display_photo', display)
    monkeypatch.setattr(slideshow.pygame.time, 'get_ticks', lambda: clock[0])
    monkeypatch.setattr(slideshow.pygame.time, 'wait', wait)
    monkeypatch.setattr(slideshow, 'handle_events', lambda: len(shown) < 2)
    slideshow.show_slideshow()
    assert shown[1] - shown[0] == 1000


def test_unreadable_only_cache_waits_and_reports_error(app, monkeypatch, immediate_loader):
    from client.status import RuntimeStatus
    status = RuntimeStatus()
    photo = app.cache / 'kids/broken.jpg'
    photo.parent.mkdir(parents=True)
    photo.write_bytes(b'not an image')
    slideshow = app.slideshow
    waits = []
    prepares = Mock(wraps=slideshow.prepare_photo)
    monkeypatch.setattr(slideshow, 'prepare_photo', prepares)
    monkeypatch.setattr(slideshow.pygame.time, 'wait', lambda duration: waits.append(duration))
    monkeypatch.setattr(slideshow, 'handle_events', lambda: len(waits) < 4)
    slideshow.show_slideshow(status=status)
    assert waits and all(duration > 0 for duration in waits)
    assert prepares.call_count == 1  # Do not repeatedly decode the same corrupt bytes.
    assert 'broken.jpg' in status.snapshot()[0]['message']


def test_server_restart_retains_error_history_and_does_not_touch_display(monkeypatch):
    from client.control import server
    from client.status import RuntimeStatus
    status = RuntimeStatus()
    healthy = Event()
    attempts = []
    class Panel:
        def __init__(self, *args):
            self.port = args[2]
            self._thread = Mock()
            self._thread.is_alive.return_value = False
        def start(self):
            attempts.append(1)
            if len(attempts) == 1:
                raise OSError('Port occupied')
        def check_running(self):
            healthy.set()
        def stop(self):
            pass
    monkeypatch.setattr(server, 'ControlServer', Panel)
    monkeypatch.setattr(server, 'control_url', lambda *args: 'http://192.168.1.2:8000')
    supervisor = server.ControlSupervisor(object(), '0.0.0.0', 8000, status, retry_seconds=.01)
    supervisor.start()
    try:
        assert healthy.wait(2)
    finally:
        supervisor.stop()
    assert attempts == [1, 1]
    issue = status.snapshot()[0]
    assert 'Port occupied' in issue['message']
    assert not issue['active']
    assert supervisor.url == 'http://192.168.1.2:8000'


def test_red_error_history_below_controls_is_escaped_and_retained_after_recovery():
    from fastapi.testclient import TestClient
    from client.control.app import create_app
    from client.settings import RuntimeSettings
    from client.status import RuntimeStatus
    status = RuntimeStatus()
    status.report('Sync', 'Invalid checksum: <photo> & retrying')
    with TestClient(create_app(RuntimeSettings(5), status)) as browser:
        response = browser.get('/')
        assert 'style="color: red"' in response.text
        assert response.text.index('Error history') > response.text.rindex('</form>')
        assert 'Invalid checksum: &lt;photo&gt; &amp; retrying' in response.text
        assert '(active)' in response.text
        status.clear('Sync')
        assert '(recovered)' in browser.get('/').text
        assert browser.post('/settings', data={'display_seconds': '3'}).status_code == 200


def test_cached_runtime_opens_while_initial_sync_is_blocked(app, monkeypatch):
    from client import runtime
    entered = Event()
    completed = Event()
    def blocked_sync(queue, *, stop_event, status):
        entered.set()
        stop_event.wait(2)
        completed.set()
    def display(*args, **kwargs):
        assert entered.wait(2)
        assert not completed.is_set(), 'Playback waited for initial sync'
    monkeypatch.setattr(app.sync, 'sync_photos', blocked_sync)
    monkeypatch.setattr(runtime, 'ControlSupervisor', Mock(return_value=Mock()))
    monkeypatch.setattr(app.slideshow, 'show_slideshow', display)
    runtime.run_display(sync_interval=30)
    assert completed.is_set()  # Shutdown signalled and joined the worker.


def test_unexpected_control_request_error_is_recorded_and_next_request_recovers():
    from fastapi.testclient import TestClient
    from client.control.app import create_app
    from client.settings import RuntimeSettings
    from client.status import RuntimeStatus
    folders = Mock(side_effect=[OSError('Temporary server error'), []])
    status = RuntimeStatus()
    with TestClient(create_app(RuntimeSettings(5, folders=folders), status), raise_server_exceptions=False) as browser:
        failed = browser.get('/')
        assert failed.status_code == 500
        assert 'Temporary server error' in failed.text
        assert 'style="color: red"' in failed.text
        recovered = browser.get('/')
        assert recovered.status_code == 200
        assert '(recovered)' in recovered.text
