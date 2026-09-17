"""Keep display, synchronization, and the web server independent at runtime."""

import logging
import os
from queue import SimpleQueue
import sys
from threading import Event

from .cache import CacheIndex
from .control.app import create_app
from .control.server import ControlSupervisor
from .settings import RuntimeSettings
from .status import RuntimeStatus


logger = logging.getLogger(__name__)


def _restart_process(command):
    """Replace this process after its display and worker cleanup has finished."""
    logger.info("Restarting DigitalFrame after software update")
    os.execv(sys.executable, [sys.executable, "-m", "client", command])


def run_display(*, sync_interval=None):
    from .config import CACHE_DIR, CONTROL_HOST, CONTROL_PORT, CONTROL_URL_DISPLAY_SECONDS, DISPLAY_SECONDS
    from .slideshow import show_slideshow
    from .config import WIFI_SETUP_ENABLED, WIFI_SOCKET

    status = RuntimeStatus()
    restart_requested = Event()
    index = CacheIndex(CACHE_DIR)
    settings = RuntimeSettings(DISPLAY_SECONDS, folders=index.folders)
    network = None
    if WIFI_SETUP_ENABLED:
        if CONTROL_HOST != "0.0.0.0":
            status.report("Wi-Fi setup", "Set CONTROL_HOST=0.0.0.0 to make the panel reachable on the setup hotspot.")
        else:
            from .network.client import NetworkClient
            network = NetworkClient(WIFI_SOCKET, CONTROL_PORT)
            network.start()
    network_args = {"network": network} if network is not None else {}
    panel = ControlSupervisor(create_app(
        settings, status, index=index, request_restart=restart_requested.set, **network_args),
                              CONTROL_HOST, CONTROL_PORT, status, **network_args)
    new_photos = SimpleQueue()
    worker = None
    panel.start()
    try:
        if sync_interval is not None:
            from .main import SyncWorker
            worker = SyncWorker(new_photos, status, index, sync_interval, **network_args)
            worker.start()
        show_slideshow(settings, control_url=lambda: panel.url,
                       url_display_seconds=CONTROL_URL_DISPLAY_SECONDS,
                       new_photos=new_photos, status=status, index=index,
                       stop_event=restart_requested, **network_args)
    finally:
        if worker is not None:
            worker.stop()
        panel.stop()
        if network is not None:
            network.stop()
    if restart_requested.is_set():
        _restart_process("run" if sync_interval is not None else "slideshow")


def main():
    from .logging_config import configure_logging

    configure_logging()
    run_display()
