import logging
import threading
import time
from functools import partial
from queue import SimpleQueue

from .sync import sync_photos
from .runtime import run_display
from .config import SYNC_INTERVAL
from .logging_config import configure_logging


logger = logging.getLogger(__name__)


def sync_loop(new_photos=None):
    logger.debug(
        "Background sync loop started with a %s-second interval",
        SYNC_INTERVAL,
    )

    while True:
        time.sleep(SYNC_INTERVAL)
        sync_photos(new_photos=new_photos)


def start_sync(new_photos=None):
    sync_photos(new_photos=new_photos)

    sync_thread = threading.Thread(
        target=sync_loop,
        args=(new_photos,),
        daemon=True,
        name="photo-sync",
    )
    sync_thread.start()
    logger.debug("Background sync thread started")


def main():
    configure_logging()
    logger.info("DigitalFrame client starting")
    new_photos = SimpleQueue()
    try:
        run_display(before_display=partial(start_sync, new_photos), new_photos=new_photos)
    finally:
        logger.info("DigitalFrame client stopped")


if __name__ == "__main__":
    main()
