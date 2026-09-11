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

    run = Mock()
    sync = Mock()
    slideshow = Mock()
    monkeypatch.setattr(app.main, "main", run)
    monkeypatch.setattr(app.sync, "sync_photos", sync)
    monkeypatch.setattr(app.slideshow, "show_slideshow", slideshow)

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
        assert "--extra display" in result.output


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
    monkeypatch.setattr(app.main, "show_slideshow", lambda: calls.append("slideshow"))

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
