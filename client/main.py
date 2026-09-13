"""Run cached playback immediately while one worker synchronizes Drive."""

import logging
import threading

from .runtime import run_display
from .logging_config import configure_logging

logger = logging.getLogger(__name__)


class SyncWorker:
    def __init__(self, new_photos, status, index, interval):
        self.new_photos, self.status, self.index = new_photos, status, index
        self.interval = interval
        self.stop_event = threading.Event()
        self.thread = threading.Thread(target=self._run, name="photo-sync", daemon=True)

    def start(self):
        self.thread.start()

    def _run(self):
        while not self.stop_event.is_set():
            try:
                # Missing cloud configuration or SSL/network errors must not
                # prevent a frame with cached photos from running.
                from .sync import sync_photos
                sync_photos(self.new_photos, stop_event=self.stop_event, status=self.status)
                self.index.refresh(force=True)
            except Exception as exc:
                logger.exception("Background sync failed; cached playback continues")
                self.status.report_exception("Sync", exc)
            if self.stop_event.wait(self.interval):
                break

    def stop(self):
        self.stop_event.set()
        self.thread.join(timeout=5)
        if self.thread.is_alive():
            logger.warning("Sync is still finishing a bounded network operation during shutdown")


def main():
    from .config import SYNC_INTERVAL

    configure_logging()
    logger.info("DigitalFrame client starting")
    try:
        run_display(sync_interval=SYNC_INTERVAL)
    finally:
        logger.info("DigitalFrame client stopped")


if __name__ == "__main__":
    main()
