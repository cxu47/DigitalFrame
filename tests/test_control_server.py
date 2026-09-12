"""Deterministic server readiness, failure propagation, and bounded cleanup."""

import threading
from unittest.mock import Mock

import pytest

from client.control import server as control


@pytest.fixture
def server(monkeypatch):
    backend = Mock(started=False, should_exit=False, force_exit=False)
    listener = Mock()
    listener.getsockname.return_value = ("0.0.0.0", 8000)
    backend.servers = [Mock(sockets=[listener])]
    monkeypatch.setattr(control, "control_url", lambda host, port: f"http://192.168.1.42:{port}")
    monkeypatch.setattr(control.uvicorn, "Server", lambda config: backend)
    instance = control.ControlServer(object(), "0.0.0.0", 8000, startup_timeout=0.03,
                                     shutdown_timeout=0.1)
    return instance, backend


def test_server_readiness_and_shutdown(server, caplog):
    panel, backend = server

    def run():
        backend.started = True
        while not backend.should_exit:
            threading.Event().wait(0.001)

    backend.run.side_effect = run
    with caplog.at_level("INFO"):
        panel.start()
    assert panel.url == "http://192.168.1.42:8000"
    assert panel.url in caplog.text
    assert "<frame-lan-ip>" not in caplog.text
    panel.check_running()
    panel.stop()
    assert not panel._thread.is_alive()
    assert backend.should_exit


@pytest.mark.parametrize("error", [OSError("Address already in use"), SystemExit(1)])
def test_bind_failure_is_propagated_and_thread_is_cleaned_up(server, error):
    panel, backend = server
    backend.run.side_effect = error
    with pytest.raises(RuntimeError, match="could not start on 0.0.0.0:8000"):
        panel.start()
    assert not panel._thread.is_alive()
    assert backend.should_exit


def test_startup_timeout_requests_shutdown(server):
    panel, backend = server

    def run():
        while not backend.should_exit:
            threading.Event().wait(0.001)

    backend.run.side_effect = run
    with pytest.raises(RuntimeError, match="startup timed out"):
        panel.start()
    assert not panel._thread.is_alive()


def test_unexpected_exit_is_reported(server):
    panel, backend = server
    panel._finished.set()
    with pytest.raises(RuntimeError, match="stopped unexpectedly"):
        panel.check_running()


def test_shutdown_join_is_bounded(server, caplog):
    panel, backend = server
    panel._thread = Mock()
    panel._thread.is_alive.return_value = True
    panel.stop()
    panel._thread.join.assert_called_once_with(timeout=0.1)
    assert backend.force_exit
    assert "did not stop" in caplog.text


def test_address_detection_failure_keeps_server_running(server, monkeypatch, caplog):
    panel, backend = server
    monkeypatch.setattr(control, "control_url", lambda host, port: None)

    def run():
        backend.started = True
        while not backend.should_exit:
            threading.Event().wait(0.001)

    backend.run.side_effect = run
    try:
        panel.start()
        panel.check_running()
        assert panel.url is None
        assert "no LAN address could be detected" in caplog.text
        assert "<frame-lan-ip>" not in caplog.text
    finally:
        panel.stop()
