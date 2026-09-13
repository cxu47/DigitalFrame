"""Prepare at most one upcoming image without calling SDL from a worker."""

from concurrent.futures import Future
from dataclasses import dataclass
from queue import Queue
from threading import Thread


@dataclass
class PreparedPhoto:
    pixels: bytes
    size: tuple[int, int]
    signature: tuple


class PhotoChanged(OSError):
    """A sync replaced the source while its pixels were being prepared."""


def file_signature(path):
    stat = path.stat()
    return (stat.st_dev, stat.st_ino, stat.st_size, stat.st_mtime_ns)


class PhotoLoader:
    def __init__(self, prepare):
        self.prepare = prepare
        self._requests = Queue(maxsize=1)
        self._thread = Thread(target=self._run, name="photo-loader", daemon=True)
        self._thread.start()

    def submit(self, path, size):
        future = Future()
        self._requests.put_nowait((future, path, size))
        return future

    def _run(self):
        while True:
            request = self._requests.get()
            if request is None:
                return
            future, path, size = request
            if future.set_running_or_notify_cancel():
                try:
                    future.set_result(self.prepare(path, size))
                except Exception as exc:
                    future.set_exception(exc)
            # Release the previous pixel buffer while waiting for another job.
            del request, future, path, size

    def close(self):
        self._requests.put(None)
        self._thread.join(timeout=5)
        return not self._thread.is_alive()
