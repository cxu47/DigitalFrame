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
SETUP_HOTSPOT_PASSWORD = "jamesbond"


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
            changed = False
            if not data.get("ap_ssid"):
                data["ap_ssid"] = f"DigitalFrame-{secrets.token_hex(2).upper()}"
                changed = True
            if data.get("ap_password") != SETUP_HOTSPOT_PASSWORD:
                data["ap_password"] = SETUP_HOTSPOT_PASSWORD
                changed = True
            if changed:
                self.store.save()
            self.publish(ap_ssid=data["ap_ssid"], ap_password=data["ap_password"],
                         ap_address=data.get("ap_address", ""))
            # A saved OS connection must not choose a radio on the user's
            # behalf.  Scan while Netplan still owns the link, then take the
            # radio for the setup hotspot.  Only an access point explicitly
            # selected in the panel may move this run into the online state.
            self.access_point("Set up Wi-Fi.")
        except Exception:
            self.unavailable()

    def unavailable(self):
        self.next_check = float("inf")
        self.publish(state="unavailable", address="", message="Wi-Fi setup unavailable.")

    def check_online(self):
        info = self.backend.upstream()
        if info:
            self.backend.block_forwarding(False)
            if self.store.data.get("waiting") is not False:
                self.store.data["waiting"] = False
                self.store.save()
            self.publish(state="online", address=info["address"], ssid=info["ssid"],
                         message="Wi-Fi connected. Setup becomes available if the link is lost.")
            self.next_check = self.clock() + self.interval
        else:
            self.access_point()

    def access_point(self, message="Wi-Fi unavailable — cached slideshow continues."):
        self.next_check = float("inf")
        # Commit the recovery intention before making any disruptive change.
        self.store.data["waiting"] = True
        self.store.save()
        self.publish(state="starting_ap", address="", message="Starting Wi-Fi setup...")
        points = self.snapshot.access_points
        try:
            try:
                scanned = self.backend.scan_access_points()
                if scanned:
                    points = scanned
            except Exception:
                pass
            address = self.backend.ensure_access_point(self.store)
            self.store.data["ap_address"] = address
            self.store.save()
            self.publish(state="ap", address=address, ap_address=address,
                         access_points=points, message=message)
        except Exception:
            try:
                self.backend.restore()
            except Exception:
                pass
            self.unavailable()

    def reserve(self, ssid, bssid, password):
        validate_credentials(ssid, password, bssid)
        with self.condition:
            if not self.snapshot.can_submit or self.pending is not None:
                raise NetworkError("Wi-Fi setup is not available now. Refresh the page for its current status.")
            operation = secrets.token_urlsafe(24)
            self.pending = {"id": operation, "kind": "connect", "ssid": ssid,
                            "bssid": bssid, "password": password,
                            "expires": self.clock() + 15, "ready": None}
            self.publish(state="connecting", message="Preparing your Wi-Fi connection attempt. Cached playback continues.")
            self.condition.notify_all()
            return operation

    def reserve_refresh(self):
        with self.condition:
            if not self.snapshot.can_refresh or self.pending is not None:
                raise NetworkError("Wi-Fi scanning is not available now. Reconnect and refresh the page.")
            operation = secrets.token_urlsafe(24)
            self.pending = {"id": operation, "kind": "refresh",
                            "expires": self.clock() + 15, "ready": None}
            self.publish(state="refreshing",
                         message="Preparing a fresh Wi-Fi scan. The setup hotspot will briefly disconnect.")
            self.condition.notify_all()
            return operation

    def commit(self, operation):
        with self.condition:
            if self.pending is None or not secrets.compare_digest(self.pending["id"], operation):
                raise NetworkError("This Wi-Fi request has expired. Refresh and try again.")
            if self.pending["ready"] is None:
                self.pending["ready"] = self.clock() + 5
                logger.info("Wi-Fi request committed: %s", self.pending["kind"])
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
                if pending["kind"] == "refresh":
                    self.publish(message="Scanning for all nearby Wi-Fi access points.")
                    self.backend.restore()
                    self.access_point("Scan refreshed. Choose an access point and enter its password.")
                else:
                    self.publish(message="Trying your Wi-Fi. Association and DHCP may take up to one minute.")
                    info = self.backend.connect(
                        pending["ssid"], pending["bssid"], pending["password"], self.store)
                    if info:
                        self.store.data["waiting"] = False
                        self.store.save()
                        self.publish(state="online", ssid=info["ssid"], address=info["address"],
                                     message="Connected. Rejoin your home Wi-Fi and open the URL on the slideshow.")
                        self.next_check = self.clock() + self.interval
                    else:
                        message = getattr(self.backend, "last_failure", "") or (
                            "Could not connect with internet access. Check the password and try again.")
                        self.access_point(message)
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
