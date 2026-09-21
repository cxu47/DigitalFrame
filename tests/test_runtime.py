"""Check command entry points and orchestration without a live worker thread."""

import os
from pathlib import Path
import subprocess
import sys
from unittest.mock import Mock

import pytest
from typer.testing import CliRunner


def test_help_and_no_arguments_work_without_config_or_display():
    # A fresh interpreter catches accidental eager application imports.
    script = """
import importlib.abc
import sys

class NoRuntimeImports(importlib.abc.MetaPathFinder):
    def find_spec(self, fullname, path=None, target=None):
        if fullname in {'client.player', 'client.config', 'client.main', 'client.sync', 'client.slideshow'}:
            raise AssertionError(f'Help imported {fullname}')

sys.meta_path.insert(0, NoRuntimeImports())
from client.cli import main
main(sys.argv[1:])
"""
    env = os.environ.copy()
    for name in ("CACHE_FOLDER", "SECRETS_FOLDER", "OSS_CREDENTIALS_FILE",
                 "DISPLAY_SECONDS", "IDLE_SECONDS", "SYNC_INTERVAL"):
        env.pop(name, None)
    for args in ([], ["--help"]):
        result = subprocess.run(
            [sys.executable, "-c", script, *args], env=env,
            cwd=Path(__file__).resolve().parents[1], capture_output=True, text=True, timeout=10,
        )
        assert result.returncode == 0, result.stderr
        assert all(command in result.stdout for command in ("run", "sync", "slideshow"))


@pytest.mark.parametrize("command", ["run", "sync", "slideshow"])
def test_commands_dispatch_to_the_expected_workflow(app, monkeypatch, command):
    from client import cli
    from client import runtime

    run = Mock()
    sync = Mock()
    slideshow = Mock()
    monkeypatch.setattr(app.main, "main", run)
    monkeypatch.setattr(app.sync, "sync_photos", sync)
    monkeypatch.setattr(runtime, "main", slideshow)
    monkeypatch.setattr(cli, "require_mpv", Mock())

    result = CliRunner().invoke(cli.app, [command])

    assert result.exit_code == 0, result.exception
    for name, callback in (("run", run), ("sync", sync), ("slideshow", slideshow)):
        assert callback.call_count == (1 if name == command else 0)


def test_sync_works_without_mpv_and_display_commands_explain_missing_dependency(app, monkeypatch):
    from client import cli

    sync = Mock()
    monkeypatch.setattr(cli.shutil, "which", lambda name: None)
    monkeypatch.setattr(app.sync, "sync_photos", sync)
    runner = CliRunner()

    assert runner.invoke(cli.app, ["sync"]).exit_code == 0
    sync.assert_called_once()
    for command in ("run", "slideshow"):
        result = runner.invoke(cli.app, [command])
        assert result.exit_code == 1
        assert "mpv executable is required" in result.output
        assert "uv sync --locked --no-dev" in result.output


@pytest.mark.parametrize('failure_stage', [None, 'display', 'interrupt'])
def test_runtime_starts_workers_without_waiting_for_sync_and_always_stops_them(app, monkeypatch, failure_stage):
    from fastapi.testclient import TestClient
    from client import runtime
    calls = []
    class Panel:
        url = 'http://192.168.1.42:8000'
        def __init__(self, web_app, host, port, status):
            self.browser = TestClient(web_app)
        def start(self):
            calls.append('panel')
            assert 'All — 0 pictures — updated unknown' in self.browser.get('/').text
            self.browser.post('/settings', data={'display_seconds': '10'})
        def stop(self):
            calls.append('panel stop')
            self.browser.close()
    class Worker:
        def __init__(self, queue, status, index, interval, *, settings):
            assert interval == 30
        def start(self):
            calls.append('worker scheduled')
        def stop(self):
            calls.append('worker stop')
    def display(settings, *, control_url, url_display_seconds, new_photos, status, index,
                stop_event):
        calls.append('display')
        assert settings.display_seconds == 10
        assert control_url() == Panel.url
        assert not stop_event.is_set()
        if failure_stage == 'display':
            raise RuntimeError('display failed')
        if failure_stage == 'interrupt':
            raise KeyboardInterrupt
    monkeypatch.setattr(runtime, 'ControlSupervisor', Panel)
    monkeypatch.setattr(app.main, 'SyncWorker', Worker)
    monkeypatch.setattr(app.slideshow, 'show_slideshow', display)
    if failure_stage:
        with pytest.raises(KeyboardInterrupt if failure_stage == 'interrupt' else RuntimeError):
            runtime.run_display(sync_interval=30)
    else:
        runtime.run_display(sync_interval=30)
    assert calls == ['panel', 'worker scheduled', 'display', 'worker stop', 'panel stop']


def test_requested_restart_cleans_up_then_reexecs_same_workflow(app, monkeypatch):
    from client import runtime

    calls = []
    panel = Mock()
    panel.url = "http://192.168.1.42:8000"
    panel.start.side_effect = lambda: calls.append("panel start")
    panel.stop.side_effect = lambda: calls.append("panel stop")
    worker = Mock()
    worker.start.side_effect = lambda: calls.append("worker start")
    worker.stop.side_effect = lambda: calls.append("worker stop")

    def make_app(settings, status, **kwargs):
        kwargs["request_restart"]()
        return object()

    def display(*args, stop_event, **kwargs):
        calls.append("display")
        assert stop_event.is_set()

    restart = Mock(side_effect=lambda command: calls.append(f"restart {command}"))
    monkeypatch.setattr(runtime, "create_app", make_app)
    monkeypatch.setattr(runtime, "ControlSupervisor", Mock(return_value=panel))
    monkeypatch.setattr(app.main, "SyncWorker", Mock(return_value=worker))
    monkeypatch.setattr(app.slideshow, "show_slideshow", display)
    monkeypatch.setattr(runtime, "_restart_process", restart)

    runtime.run_display(sync_interval=30)

    assert calls == [
        "panel start", "worker start", "display", "worker stop", "panel stop", "restart run",
    ]
    restart.assert_called_once_with("run")


def test_restart_process_uses_current_environment_without_reboot(monkeypatch):
    from client import runtime

    execute = Mock()
    monkeypatch.setattr(runtime.os, "execv", execute)
    monkeypatch.setattr(runtime.sys, "executable", "/frame/.venv/bin/python")
    monkeypatch.setenv("DISPLAY_SECONDS", "5")
    monkeypatch.setenv("SELECTED_FOLDER", "old")
    monkeypatch.setenv("SELECTED_MONTHS", "2026-09")
    monkeypatch.setenv("VIEW_MODE", "months")

    runtime._restart_process("slideshow")

    assert "DISPLAY_SECONDS" not in runtime.os.environ
    assert "SELECTED_FOLDER" not in runtime.os.environ
    assert "SELECTED_MONTHS" not in runtime.os.environ
    assert "VIEW_MODE" not in runtime.os.environ
    execute.assert_called_once_with(
        "/frame/.venv/bin/python",
        ["/frame/.venv/bin/python", "-m", "client", "slideshow"],
    )


def test_cache_only_runtime_does_not_sync(app, monkeypatch):
    from client import runtime
    panel = Mock()
    display = Mock()
    sync = Mock(side_effect=AssertionError('Cache-only display accessed OSS'))
    monkeypatch.setattr(runtime, 'ControlSupervisor', Mock(return_value=panel))
    monkeypatch.setattr(app.slideshow, 'show_slideshow', display)
    monkeypatch.setattr(app.sync, 'sync_photos', sync)
    runtime.main()
    sync.assert_not_called()
    display.assert_called_once()
    panel.stop.assert_called_once()


def test_background_ssl_failure_retries_and_stop_wakes_long_interval(app, monkeypatch):
    from queue import SimpleQueue
    from threading import Event
    import ssl
    from client.status import RuntimeStatus
    status = RuntimeStatus()
    retried = Event()
    attempts = []
    def sync(queue, *, stop_event, status):
        attempts.append(1)
        if len(attempts) == 1:
            raise ssl.SSLError('Wi-Fi lost')
        retried.set()
        stop_event.set()
    monkeypatch.setattr(app.sync, 'sync_photos', sync)
    worker = app.main.SyncWorker(SimpleQueue(), status, Mock(), .01)
    worker.start()
    assert retried.wait(2)
    worker.stop()
    assert not worker.thread.is_alive()
    assert len(attempts) == 2
    assert 'SSLError' in status.snapshot()[0]['message']
    worker = app.main.SyncWorker(SimpleQueue(), status, Mock(), 3600)
    worker.start()
    worker.stop()
    assert not worker.thread.is_alive()


def test_sync_cli_has_nonzero_exit_on_network_failure(app, monkeypatch):
    from client import cli
    monkeypatch.setattr(app.sync, 'list_albums', Mock(side_effect=ConnectionError('Offline')))
    result = CliRunner().invoke(cli.app, ['sync'])
    assert result.exit_code == 1
    assert 'Offline' in result.output


@pytest.mark.parametrize('command', ['slideshow', 'sync'])
def test_configuration_is_only_required_for_relevant_workflow(command):
    env = os.environ.copy()
    if command == 'slideshow':
        for key in ['SECRETS_FOLDER', 'OSS_CREDENTIALS_FILE', 'SYNC_INTERVAL']:
            env.pop(key, None)
        code = 'import client.slideshow; import client.runtime'
    else:
        for key in ['DISPLAY_SECONDS', 'IDLE_SECONDS', 'CONTROL_HOST', 'CONTROL_PORT']:
            env[key] = 'invalid-unused-value'
        code = 'import client.sync'
    result = subprocess.run([sys.executable, '-c', code], env=env, capture_output=True, text=True, timeout=10)
    assert result.returncode == 0, result.stderr
