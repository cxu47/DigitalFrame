"""Bounded startup and shutdown for one in-process Uvicorn server."""

import logging
import threading
import time

import uvicorn

from .address import control_url


logger = logging.getLogger(__name__)


class ControlServer:
    def __init__(self, app, host: str, port: int, *, startup_timeout=5.0, shutdown_timeout=5.0):
        self.host, self.port = host, port
        self.url = None
        self.startup_timeout = startup_timeout
        self.shutdown_timeout = shutdown_timeout
        self.server = uvicorn.Server(uvicorn.Config(
            app, host=host, port=port, workers=1, reload=False,
            loop="asyncio", http="h11", ws="none", log_config=None,
            timeout_graceful_shutdown=shutdown_timeout,
        ))
        self._error = None
        self._finished = threading.Event()
        self._thread = threading.Thread(target=self._run, name="control-panel", daemon=True)

    def _run(self):
        try:
            self.server.run()
        except BaseException as exc:
            # Uvicorn reports bind failures with SystemExit in this worker thread.
            self._error = exc
        finally:
            self._finished.set()

    def start(self):
        self._thread.start()
        deadline = time.monotonic() + self.startup_timeout
        try:
            while not self.server.started:
                if self._finished.is_set():
                    raise RuntimeError(f"Control panel could not start on {self.host}:{self.port}.") from self._error
                remaining = deadline - time.monotonic()
                if remaining <= 0:
                    raise RuntimeError(f"Control panel startup timed out on {self.host}:{self.port}.")
                self._finished.wait(min(0.01, remaining))
            self.check_running()
        except BaseException:
            self.stop()
            raise
        # Read the actual listener, including an OS-selected port when port=0.
        listener = self.server.servers[0].sockets[0].getsockname()
        self.url = control_url(listener[0], listener[1])
        if self.url:
            logger.info("Control panel: %s", self.url)
        else:
            logger.warning("Control panel listening on %s:%s, but no LAN address could be detected",
                           self.host, self.port)

    def check_running(self):
        if self._finished.is_set():
            raise RuntimeError("Control panel stopped unexpectedly; stopping the slideshow.") from self._error

    def stop(self):
        self.server.should_exit = True
        self._thread.join(timeout=self.shutdown_timeout)
        if self._thread.is_alive():
            self.server.force_exit = True
            logger.error("Control panel did not stop within %.1f seconds", self.shutdown_timeout)
