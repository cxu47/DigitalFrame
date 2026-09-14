"""Unprivileged Unix-socket client. Local status subscriptions never probe the internet."""

import json
import socket
from threading import Condition, Event, Thread

from .state import NetworkError, NetworkSnapshot


class NetworkClient:
    def __init__(self, path, port=8000):
        self.path = str(path)
        self.control_port = port
        self.generation = 0
        self.condition = Condition()
        self._snapshot = NetworkSnapshot()
        self.offline = Event()
        self.offline.set()
        self.stopping = Event()
        self._socket = None
        self.thread = Thread(target=self._watch, daemon=True, name="network-status")

    def start(self):
        self.thread.start()

    def snapshot(self):
        with self.condition:
            return self._snapshot

    def _publish(self, snapshot):
        with self.condition:
            if self._snapshot.online and not snapshot.online:
                self.generation += 1
            self._snapshot = snapshot
            if snapshot.online:
                self.offline.clear()
            else:
                self.offline.set()
            self.condition.notify_all()

    def _open(self):
        connection = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
        try:
            connection.settimeout(5)
            connection.connect(self.path)
            return connection
        except Exception:
            connection.close()
            raise

    def request(self, operation, **values):
        try:
            with self._open() as connection:
                connection.sendall((json.dumps({"op": operation, **values}) + "\n").encode())
                with connection.makefile("rb") as stream:
                    result = json.loads(stream.readline(8193))
            if not result.get("ok"):
                raise NetworkError(result.get("error", "Wi-Fi request was not accepted."))
            return result
        except NetworkError:
            raise
        except Exception:
            raise NetworkError("The Wi-Fi helper is unavailable. Cached playback continues.") from None

    def reserve(self, ssid, password):
        return self.request("reserve", ssid=ssid, password=password)["operation"]

    def commit(self, operation):
        try:
            self.request("commit", operation=operation)
        except NetworkError:
            # The helper expires the reservation without dropping the hotspot.
            pass

    def suspect(self):
        try:
            self.request("check")
        except NetworkError:
            pass

    def _watch(self):
        while not self.stopping.is_set():
            try:
                with self._open() as connection:
                    self._socket = connection
                    connection.settimeout(40)
                    connection.sendall(b'{"op":"watch"}\n')
                    with connection.makefile("rb") as stream:
                        while not self.stopping.is_set():
                            line = stream.readline(8193)
                            if not line or len(line) > 8192:
                                raise OSError("Status stream closed")
                            self._publish(NetworkSnapshot(**json.loads(line)))
            except Exception:
                previous = self.snapshot()
                self._publish(NetworkSnapshot(state="unavailable", ap_ssid=previous.ap_ssid,
                    ap_password=previous.ap_password, ap_address=previous.ap_address,
                    message="Wi-Fi helper unavailable. Cached playback continues."))
            finally:
                self._socket = None
            # Local service recovery only; never activates Wi-Fi or probes upstream.
            self.stopping.wait(2)

    def wait_online(self, stop_event):
        with self.condition:
            self.condition.wait_for(lambda: self._snapshot.online or stop_event.is_set() or self.stopping.is_set())
            return self._snapshot.online and not stop_event.is_set() and not self.stopping.is_set()

    def wake(self):
        with self.condition:
            self.condition.notify_all()

    def wait_interval(self, seconds, stop_event):
        with self.condition:
            self.condition.wait_for(lambda: not self._snapshot.online or stop_event.is_set(), timeout=seconds)

    def stop(self):
        self.stopping.set()
        self.wake()
        connection = self._socket
        if connection is not None:
            try:
                connection.shutdown(socket.SHUT_RDWR)
            except OSError:
                pass
        self.thread.join(timeout=6)
