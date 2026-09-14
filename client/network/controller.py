"""Serialized, testable Wi-Fi recovery policy; hardware operations run in one worker."""

from dataclasses import replace
import json
import logging
import os
from pathlib import Path
import secrets
from threading import Condition
import time

from .state import NetworkError, NetworkSnapshot, validate_credentials

logger = logging.getLogger(__name__)


class StateFile:
    def __init__(self, path):
        self.path = Path(path)
        try:
            self.data = json.loads(self.path.read_text())
            if not isinstance(self.data, dict):
                raise ValueError
        except FileNotFoundError:
            self.data = {}
        except (ValueError, OSError):
            # A damaged recovery record must never cause an upstream retry.
            self.data = {"waiting": True}

    def save(self):
        self.path.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
        temporary = self.path.with_suffix(".part")
        fd = os.open(temporary, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
        with os.fdopen(fd, "w") as target:
            json.dump(self.data, target)
            target.flush()
            os.fsync(target.fileno())
        temporary.replace(self.path)


class NetworkController:
    def __init__(self, backend, store, *, clock=time.monotonic, interval=30):
        self.backend, self.store = backend, store
        self.clock, self.interval = clock, interval
        self.condition = Condition()
        self.snapshot = NetworkSnapshot()
        self.pending = None
        self.next_check = float("inf")
        self.changed = False
        self.recover_requested = False
        self.stopped = False

    def publish(self, **values):
        with self.condition:
            snapshot = replace(self.snapshot, **values)
            if snapshot != self.snapshot:
                if snapshot.state != self.snapshot.state:
                    logger.info("Wi-Fi state: %s", snapshot.state)
                self.snapshot = replace(snapshot, revision=self.snapshot.revision + 1)
                self.condition.notify_all()

    def start(self):
        try:
            self.backend.prepare(self.store)
            data = self.store.data
            if not data.get("ap_ssid"):
                data.update(ap_ssid=f"DigitalFrame-{secrets.token_hex(2).upper()}",
                            ap_password=secrets.token_urlsafe(12))
                self.store.save()
            self.publish(ap_ssid=data["ap_ssid"], ap_password=data["ap_password"],
                         ap_address=data.get("ap_address", ""))
            if data.get("waiting"):
                self.access_point()
                return
            if not self.backend.upstream() and data.get("saved_uuid"):
                try:
                    self.backend.activate_saved(data["saved_uuid"])
                except Exception:
                    pass  # A failed boot attempt falls back to the setup hotspot.
            self.check_online()
        except Exception:
            self.unavailable()

    def unavailable(self):
        self.next_check = float("inf")
        self.publish(state="unavailable", address="",
                     message="Wi-Fi setup unavailable. Check the board adapter, NetworkManager, and helper service.")

    def check_online(self):
        info = self.backend.verify_upstream()
        if info:
            self.backend.block_forwarding(False)
            if self.store.data.get("waiting") is not False:
                self.store.data["waiting"] = False
                self.store.save()
            self.publish(state="online", address=info["address"], ssid=info["ssid"],
                         message="Already connected. Wi-Fi setup becomes available when internet is lost.")
            self.next_check = self.clock() + self.interval
        else:
            self.access_point()

    def access_point(self, message="Internet unavailable — cached slideshow continues."):
        self.next_check = float("inf")
        # Commit the recovery intention before making any disruptive change.
        self.store.data["waiting"] = True
        self.store.save()
        self.publish(state="starting_ap", address="", message="Starting the setup hotspot. Cached playback continues.")
        try:
            address = self.backend.ensure_access_point(self.store)
            self.store.data["ap_address"] = address
            self.store.save()
            self.publish(state="ap", address=address, ap_address=address, message=message)
        except Exception:
            self.unavailable()

    def reserve(self, ssid, password):
        validate_credentials(ssid, password)
        with self.condition:
            if not self.snapshot.can_submit or self.pending is not None:
                raise NetworkError("Wi-Fi setup is not available now. Refresh the page for its current status.")
            operation = secrets.token_urlsafe(24)
            self.pending = {"id": operation, "ssid": ssid, "password": password,
                            "expires": self.clock() + 15, "ready": None}
            self.publish(state="connecting", message="Preparing your Wi-Fi connection attempt. Cached playback continues.")
            self.condition.notify_all()
            return operation

    def commit(self, operation):
        with self.condition:
            if self.pending is None or not secrets.compare_digest(self.pending["id"], operation):
                raise NetworkError("This Wi-Fi request has expired. Refresh and try again.")
            if self.pending["ready"] is None:
                self.pending["ready"] = self.clock() + 2
                self.condition.notify_all()

    def event(self, *, recover=False):
        with self.condition:
            self.changed = True
            self.recover_requested = self.recover_requested or recover
            self.condition.notify_all()

    def step(self):
        """One event/timeout; offline idle time performs no backend operations."""
        with self.condition:
            pending = self.pending
            changed, self.changed = self.changed, False
            recover, self.recover_requested = self.recover_requested, False
            if pending and pending["ready"] is None:
                if self.clock() >= pending["expires"]:
                    self.pending = None
                    self.publish(state="ap", message="Wi-Fi request expired before activation. Please submit again.")
                return
            if pending:
                if self.clock() < pending["ready"]:
                    return
                self.pending = None
        try:
            if pending:
                self.publish(message="Trying your Wi-Fi. Cached playback continues.")
                # Backend owns bounded activation, candidate rollback, and persistence.
                info = self.backend.connect(pending["ssid"], pending["password"], self.store)
                if info:
                    self.store.data["waiting"] = False
                    self.store.save()
                    self.publish(state="online", ssid=info["ssid"], address=info["address"],
                                 message="Connected. Rejoin your home Wi-Fi and open the URL on the slideshow.")
                    self.next_check = self.clock() + self.interval
                else:
                    self.access_point("Could not connect with internet access. Check the SSID and password, then try again.")
            elif self.snapshot.online and (changed or self.clock() >= self.next_check):
                self.check_online()
            elif changed and self.snapshot.state == "ap" and not self.backend.ap_running():
                self.access_point()
            elif recover and self.snapshot.state == "unavailable":
                self.start()
        except Exception:
            self.access_point("Connection attempt failed. Enter your Wi-Fi details to try again.")

    def run(self):
        self.start()
        while True:
            with self.condition:
                if self.stopped:
                    return
                deadline = self.next_check
                if self.pending:
                    deadline = self.pending["ready"] or self.pending["expires"]
                if not self.changed and deadline > self.clock():
                    self.condition.wait(None if deadline == float("inf") else deadline - self.clock())
                    continue
            self.step()

    def stop(self):
        with self.condition:
            self.stopped = True
            self.condition.notify_all()
