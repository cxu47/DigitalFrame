import threading
import time

from .sync import sync_photos
from .slideshow import show_slideshow
from .config import SYNC_INTERVAL


def sync_loop():
    while True:
        time.sleep(SYNC_INTERVAL) 
        sync_photos()

def main():
    sync_photos()

    sync_thread = threading.Thread(
        target=sync_loop,
        daemon=True,
    )
    sync_thread.start()

    show_slideshow()


if __name__ == "__main__":
    main()
