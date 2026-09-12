"""Keep every test offline, headless, and separate from the frame's own files."""

import socket
from types import SimpleNamespace

import pytest


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
    return modules


@pytest.fixture
def screen(app):
    pygame = app.slideshow.pygame
    pygame.init()
    surface = pygame.display.set_mode((80, 60))
    yield surface
    pygame.quit()
