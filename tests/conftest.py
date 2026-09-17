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
        "SDL_VIDEODRIVER": "dummy",
        "SDL_AUDIODRIVER": "dummy",
        "PYGAME_HIDE_SUPPORT_PROMPT": "1",
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
    secrets = tmp_path / "secrets"
    secrets.mkdir()
    for module in (modules.config, modules.sync, modules.slideshow):
        monkeypatch.setattr(module, "CACHE_DIR", modules.cache)
    for module in (modules.config, modules.drive):
        monkeypatch.setattr(module, "GOOGLE_TOKEN_FILE", secrets / "token.json")
        monkeypatch.setattr(module, "GOOGLE_CREDENTIALS_FILE", secrets / "credentials.json")
    monkeypatch.setattr(sync, "get_drive_service", Mock(return_value=Mock()))
    return modules


@pytest.fixture
def screen(app):
    pygame = app.slideshow.pygame
    pygame.init()
    surface = pygame.display.set_mode((80, 60))
    yield surface
    pygame.quit()


@pytest.fixture
def immediate_loader(app, monkeypatch):
    """Keep clock-driven UI tests deterministic; worker overlap is tested separately."""
    from concurrent.futures import Future
    from client.preload import PreparedPhoto, file_signature
    class ImmediateLoader:
        def __init__(self, prepare):
            self.prepare = prepare
        def submit(self, path, size):
            future = Future()
            try:
                if path.stat().st_size == 0:
                    prepared = PreparedPhoto(b'\0\0\0', (1, 1), file_signature(path))
                else:
                    prepared = self.prepare(path, size)
                future.set_result(prepared)
            except Exception as exc:
                future.set_exception(exc)
            return future
        def close(self):
            return True
    monkeypatch.setattr(app.slideshow, 'PhotoLoader', ImmediateLoader)
