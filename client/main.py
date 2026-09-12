import logging
import threading
import time

from .sync import sync_photos
from .runtime import run_display
from .config import SYNC_INTERVAL
from .logging_config import configure_logging


logger = logging.getLogger(__name__)


def sync_loop():
    logger.debug(
        "Background sync loop started with a %s-second interval",
        SYNC_INTERVAL,
    )

    while True:
        time.sleep(SYNC_INTERVAL)
        sync_photos()


def start_sync():
    sync_photos()

    sync_thread = threading.Thread(
        target=sync_loop,
        daemon=True,
        name="photo-sync",
    )
    sync_thread.start()
    logger.debug("Background sync thread started")


def main():
    configure_logging()
    logger.info("DigitalFrame client starting")
    try:
        run_display(before_display=start_sync)
    finally:
        logger.info("DigitalFrame client stopped")


if __name__ == "__main__":
    main()
