import threading
import time

from .sync import sync_photos
from .slideshow import show_slideshow
from .config import SYNC_INTERVAL


def main():
    sync_photos()


if __name__ == "__main__":
    main()
