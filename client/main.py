import threading
import time

from client.sync import sync_photos
from client.slideshow import show_slideshow

SYNC_INTERVAL = 60 # 60 sec interval for sync


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
