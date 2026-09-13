"""Bounded, thread-safe error history shared by playback and the control panel."""

from collections import deque
from datetime import datetime, timezone
import errno
import socket
import ssl
from threading import Lock


def is_network_error(exc):
    """Recognize transport failures without treating disk/config errors as Wi-Fi issues."""
    seen = set()
    while exc is not None and id(exc) not in seen:
        seen.add(id(exc))
        if isinstance(exc, (ConnectionError, TimeoutError, ssl.SSLError, socket.gaierror)):
            return True
        if isinstance(exc, OSError) and exc.errno in {
            errno.ENETDOWN, errno.ENETUNREACH, errno.EHOSTUNREACH,
            errno.ECONNABORTED, errno.ECONNRESET, errno.ECONNREFUSED,
            errno.ETIMEDOUT, errno.EADDRNOTAVAIL,
        }:
            return True
        # Keep cloud/client imports out of cache-only startup. Inspect base
        # classes so Requests subclasses such as ConnectTimeout are included.
        if any((base.__module__, base.__name__) in {
            ("requests.exceptions", "ConnectionError"),
            ("requests.exceptions", "Timeout"),
            ("google.auth.exceptions", "TransportError"),
            ("httplib2", "ServerNotFoundError"),
            ("httplib2.error", "ServerNotFoundError"),
        } for base in type(exc).__mro__):
            return True
        exc = exc.__cause__ or exc.__context__
    return False


class RuntimeStatus:
    def __init__(self):
        self._lock = Lock()
        self._history = deque(maxlen=20)
        self._active = {}

    def report(self, source, message, *, network=False):
        message = str(message)
        now = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S UTC")
        with self._lock:
            current = self._active.get(source)
            if current is not None and current["message"] == message and current["network"] == network:
                current["time"] = now
                return
            if current is not None:
                current["active"] = False
            entry = {"source": source, "message": message, "time": now, "active": True, "network": network}
            self._active[source] = entry
            self._history.append(entry)

    def report_exception(self, source, exc):
        self.report(source, f"{type(exc).__name__}: {exc}", network=is_network_error(exc))

    def network_problem(self):
        with self._lock:
            return any(entry["network"] for entry in self._active.values())

    def panel_snapshot(self):
        return [entry for entry in self.snapshot() if not entry["network"]]

    def clear(self, source):
        with self._lock:
            entry = self._active.pop(source, None)
            if entry is not None:
                entry["active"] = False

    def snapshot(self):
        with self._lock:
            # Active issues stay visible even if other history reaches its limit.
            entries = list(self._history)
            entries.extend(item for item in self._active.values() if item not in entries)
            return [dict(item) for item in reversed(entries)]
