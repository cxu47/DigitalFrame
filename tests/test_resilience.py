"""Real thread boundaries, failed servers, and visible recovery messages."""

from threading import Event
from unittest.mock import Mock

def test_unreadable_only_cache_waits_and_reports_error(app, monkeypatch):
    from client.status import RuntimeStatus
    status = RuntimeStatus()
    photo = app.cache / 'kids/broken.jpg'
    photo.parent.mkdir(parents=True)
    photo.write_bytes(b'not an image')
    slideshow = app.slideshow
    attempts = []
    original = slideshow.display_photo
    def display(player, path, prepared=None):
        attempts.append(path)
        return original(player, path, prepared)
    monkeypatch.setattr(slideshow, "display_photo", display)
    def wait(player, duration):
        if len(player.waits) >= 4:
            player.running = False
    app.FakeMPV.wait_hook = wait
    slideshow.show_slideshow(status=status)
    assert app.FakeMPV.instances[-1].waits
    assert len(attempts) == 1  # Do not repeatedly ask mpv to decode unchanged corrupt bytes.
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
