"""Share one control panel and settings instance with the main-thread display."""

from .control.app import create_app
from .control.server import ControlServer
from .settings import RuntimeSettings


def run_display(*, before_display=None, new_photos=None):
    from .config import CONTROL_HOST, CONTROL_PORT, CONTROL_URL_DISPLAY_SECONDS, DISPLAY_SECONDS
    from .slideshow import get_cached_folders, show_slideshow

    settings = RuntimeSettings(DISPLAY_SECONDS, folders=get_cached_folders)
    panel = ControlServer(create_app(settings), CONTROL_HOST, CONTROL_PORT)
    panel.start()
    try:
        if before_display is not None:
            before_display()
        panel.check_running()
        show_slideshow(settings, check_running=panel.check_running,
                       control_url=panel.url, url_display_seconds=CONTROL_URL_DISPLAY_SECONDS,
                       new_photos=new_photos)
    finally:
        panel.stop()


def main():
    from .logging_config import configure_logging

    configure_logging()
    run_display()
