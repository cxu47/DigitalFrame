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
        if fullname in {'pygame', 'client.config', 'client.main', 'client.sync', 'client.slideshow'}:
            raise AssertionError(f'Help imported {fullname}')

sys.meta_path.insert(0, NoRuntimeImports())
from client.cli import main
main(sys.argv[1:])
"""
    env = os.environ.copy()
    for name in ("CACHE_FOLDER", "SECRETS_FOLDER", "GOOGLE_CREDENTIALS_FILE", "GOOGLE_TOKEN_FILE",
                 "DISPLAY_SECONDS", "IDLE_SECONDS", "SYNC_INTERVAL", "GOOGLE_DRIVE_FOLDER_ID"):
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

    result = CliRunner().invoke(cli.app, [command])

    assert result.exit_code == 0, result.exception
    for name, callback in (("run", run), ("sync", sync), ("slideshow", slideshow)):
        assert callback.call_count == (1 if name == command else 0)


def test_sync_works_without_pygame_and_display_commands_explain_missing_dependency(app, monkeypatch):
    from client import cli

    original_import = cli.importlib.import_module

    def without_pygame(name, *args, **kwargs):
        if name == "pygame":
            raise ModuleNotFoundError("No module named 'pygame'", name="pygame")
        return original_import(name, *args, **kwargs)

    sync = Mock()
    monkeypatch.setattr(cli.importlib, "import_module", without_pygame)
    monkeypatch.setattr(app.sync, "sync_photos", sync)
    runner = CliRunner()

    assert runner.invoke(cli.app, ["sync"]).exit_code == 0
    sync.assert_called_once()
    for command in ("run", "slideshow"):
        result = runner.invoke(cli.app, [command])
        assert result.exit_code == 1
        assert "Pygame is required" in result.output
        assert "uv sync --locked --no-dev" in result.output


def test_frame_syncs_before_starting_background_worker_and_slideshow(app, monkeypatch):
    calls = []

    class Worker:
        def __init__(self, *, target, daemon, name):
            assert target is app.main.sync_loop
            assert daemon is True

        def start(self):
            calls.append("background")

    monkeypatch.setattr(app.main, "sync_photos", lambda: calls.append("initial sync"))
    monkeypatch.setattr(app.main.threading, "Thread", Worker)
    def run_display(*, before_display):
        before_display()
        calls.append("slideshow")

    monkeypatch.setattr(app.main, "run_display", run_display)

    app.main.main()

    assert calls == ["initial sync", "background", "slideshow"]


def test_background_sync_repeats_at_configured_interval(app, monkeypatch):
    calls = []

    class StopLoop(Exception):
        pass

    def sleep(seconds):
        if len(calls) == 4:
            raise StopLoop
        calls.append(seconds)

    monkeypatch.setattr(app.main, "SYNC_INTERVAL", 42)
    monkeypatch.setattr(app.main.time, "sleep", sleep)
    monkeypatch.setattr(app.main, "sync_photos", lambda: calls.append("sync"))

    with pytest.raises(StopLoop):
        app.main.sync_loop()

    assert calls == [42, "sync", 42, "sync"]


@pytest.mark.parametrize("failure_stage", [None, "sync", "display", "interrupt", "server"])
def test_panel_shares_settings_and_stops_on_every_runtime_exit(app, monkeypatch, failure_stage):
    from fastapi.testclient import TestClient
    from client import runtime

    calls = []

    class Panel:
        url = "http://192.168.1.42:8000"

        def __init__(self, web_app, host, port):
            assert (host, port) == ("0.0.0.0", 8000)
            self.browser = TestClient(web_app)

        def start(self):
            calls.append("panel")
            self.browser.post("/settings", data={"display_seconds": "10"})

        def check_running(self):
            if failure_stage == "server":
                raise RuntimeError("server failed")

        def stop(self):
            calls.append("stop")
            self.browser.close()

    def before_display():
        calls.append("sync")
        if failure_stage == "sync":
            raise RuntimeError("sync failed")

    def display(settings, *, check_running, control_url, url_display_seconds):
        calls.append("display")
        assert settings.display_seconds == 10
        assert control_url == Panel.url
        assert url_display_seconds == 30
        check_running()
        if failure_stage == "display":
            raise RuntimeError("display failed")
        if failure_stage == "interrupt":
            raise KeyboardInterrupt

    monkeypatch.setattr(runtime, "ControlServer", Panel)
    monkeypatch.setattr(app.slideshow, "show_slideshow", display)
    if failure_stage:
        exception = KeyboardInterrupt if failure_stage == "interrupt" else RuntimeError
        with pytest.raises(exception):
            runtime.run_display(before_display=before_display)
    else:
        runtime.run_display(before_display=before_display)
    assert calls[:2] == ["panel", "sync"]
    assert calls[-1] == "stop"
    assert ("display" in calls) is (failure_stage not in {"sync", "server"})


def test_cache_only_runtime_does_not_sync(app, monkeypatch):
    from client import runtime

    panel = Mock()
    display = Mock()
    sync = Mock(side_effect=AssertionError("Cache-only display accessed Drive"))
    monkeypatch.setattr(runtime, "ControlServer", Mock(return_value=panel))
    monkeypatch.setattr(app.slideshow, "show_slideshow", display)
    monkeypatch.setattr(app.sync, "sync_photos", sync)
    runtime.main()
    sync.assert_not_called()
    panel.start.assert_called_once()
    display.assert_called_once()
    panel.stop.assert_called_once()
