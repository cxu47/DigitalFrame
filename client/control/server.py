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
        self.port = listener[1]
        self.url = control_url(listener[0], listener[1])
        if self.url:
            logger.info("Control panel: %s", self.url)
        else:
            logger.warning("Control panel listening on %s:%s, but no LAN address could be detected",
                           self.host, self.port)

    def check_running(self):
        if self._finished.is_set():
            raise RuntimeError("Control panel stopped unexpectedly.") from self._error

    def stop(self):
        self.server.should_exit = True
        self._thread.join(timeout=self.shutdown_timeout)
        if self._thread.is_alive():
            self.server.force_exit = True
            logger.error("Control panel did not stop within %.1f seconds", self.shutdown_timeout)


class ControlSupervisor:
    """Retry a failed listener off the display thread and retain its error history."""

    def __init__(self, app, host, port, status, retry_seconds=15, *, network=None):
        self.app, self.host, self.port = app, host, port
        self.status = status
        self.retry_seconds = retry_seconds
        self.network = network
        self.bound_port = None
        self.url = None
        self._stop = threading.Event()
        self._thread = threading.Thread(target=self._run, name="control-supervisor", daemon=True)

    @property
    def url(self):
        if self.network is not None:
            snapshot = self.network.snapshot()
            if self.bound_port is not None and snapshot.state in {"online", "ap"} and snapshot.address:
                return f"http://{snapshot.address}:{self.bound_port}"
            return None
        return self._url

    @url.setter
    def url(self, value):
        self._url = value

    def start(self):
        self._thread.start()

    def _run(self):
        panel = None
        try:
            while not self._stop.is_set():
                try:
                    if panel is None:
                        panel = ControlServer(self.app, self.host, self.port)
                        panel.start()
                        self.bound_port = panel.port
                        if self.network is not None:
                            self.network.control_port = panel.port
                    panel.check_running()
                    self.status.clear("Control server")
                    detected = self.url if self.network is not None else control_url(self.host, self.port)
                    if detected:
                        if detected != self.url:
                            logger.info("Control panel: %s", detected)
                        self.url = detected
                        self.status.clear("Network address")
                    elif self.network is None:
                        self.status.report("Network address", "No network address is available. Cached playback continues.", network=True)
                except Exception as exc:
                    self.bound_port = None
                    logger.exception("Control server unavailable; cached playback continues")
                    self.status.report_exception("Control server", exc)
                    if panel is not None:
                        panel.stop()
                        # Never create another listener while this one is still
                        # exiting, even if its bounded shutdown timed out.
                        if not panel._thread.is_alive():
                            panel = None
                if self._stop.wait(self.retry_seconds):
                    break
        finally:
            if panel is not None:
                panel.stop()

    def stop(self):
        self._stop.set()
        self._thread.join(timeout=6)
        if self._thread.is_alive():
            logger.warning("Control server is still completing shutdown")
