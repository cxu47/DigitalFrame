"""Keep every test offline, headless, and separate from the frame's own files."""

import socket
from types import SimpleNamespace
from unittest.mock import Mock

import pytest


_ORIGINAL_SOCKET_CONNECT = socket.socket.connect


@pytest.fixture(autouse=True)
def isolated_environment(tmp_path, monkeypatch):
    settings = {
        "PYTHON_DOTENV_DISABLED": "1",
        "CACHE_FOLDER": str(tmp_path / "cache"),
        "SECRETS_FOLDER": str(tmp_path / "secrets"),
        "GOOGLE_CREDENTIALS_FILE": "credentials.json",
        "GOOGLE_TOKEN_FILE": "token.json",
        "GOOGLE_DRIVE_FOLDER_ID": "test-folder",
        "DISPLAY_SECONDS": "1",
        "CONTROL_HOST": "0.0.0.0",
        "CONTROL_PORT": "8000",
        "CONTROL_URL_DISPLAY_SECONDS": "30",
        "IDLE_SECONDS": "0.01",
        "SYNC_INTERVAL": "30",
        "LOG_LEVEL": "INFO",
    }
    for name, value in settings.items():
        monkeypatch.setenv(name, value)

    def reject_network(*args, **kwargs):
        pytest.fail("Tests must mock cloud access; a network connection was attempted")

    monkeypatch.setattr(socket.socket, "connect", reject_network)


@pytest.fixture
def allow_local_socket(monkeypatch):
    """Permit Unix-domain IPC tests while cloud/network access stays blocked elsewhere."""
    monkeypatch.setattr(socket.socket, "connect", _ORIGINAL_SOCKET_CONNECT)


@pytest.fixture
def app(tmp_path, monkeypatch, isolated_environment):
    # Import only after the environment fixture has disabled local .env loading.
    from client import config, main, slideshow, sync
    from client.storage import google_drive

    modules = SimpleNamespace(
        config=config, main=main, slideshow=slideshow, sync=sync, drive=google_drive,
    )
    modules.cache = tmp_path / "cache"
    modules.env_file = tmp_path / ".env"
    modules.env_file.write_text("DISPLAY_SECONDS=1\nSELECTED_FOLDER=\n")
    class FakeMPV:
        instances = []
        wait_hook = None

        def __init__(self, *args, **kwargs):
            self.running = True
            self.closed = False
            self.loaded = []
            self.overlays = {}
            self.waits = []
            self.stops = 0
            type(self).instances.append(self)

        def load(self, path):
            from PIL import Image
            with Image.open(path) as image:
                image.verify()
            self.loaded.append(path)

        def stop(self):
            self.stops += 1

        def set_overlay(self, overlay_id, text, *, color="white", position="top"):
            self.overlays[overlay_id] = (text, color, position)

        def clear_overlay(self, overlay_id):
            self.overlays.pop(overlay_id, None)

        def wait(self, milliseconds):
            self.waits.append(milliseconds)
            if type(self).wait_hook is not None:
                type(self).wait_hook(self, milliseconds)

        def close(self):
            self.running = False
            self.closed = True

    FakeMPV.instances.clear()
    FakeMPV.wait_hook = None
    modules.FakeMPV = FakeMPV
    monkeypatch.setattr(slideshow, "MPVPlayer", FakeMPV)
    secrets = tmp_path / "secrets"
    secrets.mkdir()
    for module in (modules.config, modules.sync, modules.slideshow):
        monkeypatch.setattr(module, "CACHE_DIR", modules.cache)
    monkeypatch.setattr(modules.config, "ENV_FILE", modules.env_file)
    for module in (modules.config, modules.drive):
        monkeypatch.setattr(module, "GOOGLE_TOKEN_FILE", secrets / "token.json")
        monkeypatch.setattr(module, "GOOGLE_CREDENTIALS_FILE", secrets / "credentials.json")
    monkeypatch.setattr(sync, "get_drive_service", Mock(return_value=Mock()))
    return modules
