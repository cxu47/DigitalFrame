"""Explicit, bounded software-update operations for the control panel."""

from __future__ import annotations

from dataclasses import dataclass
import logging
from pathlib import Path
import re
import subprocess
from threading import Lock


logger = logging.getLogger(__name__)
_SHA = re.compile(r"[0-9a-f]{40}")


@dataclass(frozen=True)
class UpdateSnapshot:
    state: str = "unchecked"
    message: str = "Updates have not been checked."
    can_apply: bool = False


class UpdateManager:
    """Run fixed update scripts only after an explicit control-panel request."""

    def __init__(self, project_dir: Path | None = None, *, check_timeout=60, apply_timeout=1800):
        self.project_dir = project_dir or Path(__file__).resolve().parents[1]
        self.check_timeout = check_timeout
        self.apply_timeout = apply_timeout
        self._state_lock = Lock()
        self._operation_lock = Lock()
        self._snapshot = UpdateSnapshot()

    def snapshot(self):
        with self._state_lock:
            return self._snapshot

    def _set(self, snapshot):
        with self._state_lock:
            self._snapshot = snapshot
        return snapshot

    @staticmethod
    def _values(output):
        values = {}
        for line in output.splitlines():
            key, separator, value = line.partition("=")
            if separator and key in {"state", "dirty", "local", "remote", "reason"}:
                values[key] = value.strip()
        return values

    @staticmethod
    def _short_sha(values, key):
        value = values.get(key, "")
        return value[:12] if _SHA.fullmatch(value) else "unknown"

    def _run(self, name, timeout):
        script = self.project_dir / "deploy" / name
        return subprocess.run(
            [str(script)], cwd=self.project_dir, capture_output=True, text=True,
            timeout=timeout, check=False,
        )

    def check(self):
        if not self._operation_lock.acquire(blocking=False):
            return self._set(UpdateSnapshot("busy", "Another update operation is already running."))
        try:
            try:
                result = self._run("check-update.sh", self.check_timeout)
            except (OSError, subprocess.TimeoutExpired) as exc:
                logger.warning("Update check could not run: %s", exc)
                return self._set(UpdateSnapshot("error", "Unable to check GitHub for updates."))
            values = self._values(result.stdout)
            state = values.get("state")
            local = self._short_sha(values, "local")
            remote = self._short_sha(values, "remote")
            dirty = values.get("dirty") == "1"
            if result.returncode != 0 or state == "error":
                logger.warning("Update check failed with status %s", result.returncode)
                return self._set(UpdateSnapshot("error", "Unable to check GitHub for updates."))
            if state == "available" and dirty:
                return self._set(UpdateSnapshot(
                    "dirty", f"Update {remote} is available, but local changes block installation."
                ))
            if state == "available":
                return self._set(UpdateSnapshot(
                    state, f"Update available: {local} → {remote}.", can_apply=True
                ))
            if state == "current":
                suffix = " The checkout has local changes." if dirty else ""
                return self._set(UpdateSnapshot(state, f"Software is current at {local}.{suffix}"))
            if state == "ahead":
                return self._set(UpdateSnapshot(
                    state, "The local checkout is ahead of release/3.x; automatic update is disabled."
                ))
            if state == "diverged":
                return self._set(UpdateSnapshot(
                    state, "The local checkout has diverged from release/3.x; automatic update is disabled."
                ))
            logger.warning("Update check returned an invalid state")
            return self._set(UpdateSnapshot("error", "Unable to interpret the update check."))
        finally:
            self._operation_lock.release()

    def apply(self):
        if not self._operation_lock.acquire(blocking=False):
            return self._set(UpdateSnapshot("busy", "Another update operation is already running."))
        try:
            if not self.snapshot().can_apply:
                return self._set(UpdateSnapshot(
                    "blocked", "Check for an available update before installing it."
                ))
            try:
                result = self._run("apply-update.sh", self.apply_timeout)
            except (OSError, subprocess.TimeoutExpired) as exc:
                logger.warning("Update install could not run: %s", exc)
                return self._set(UpdateSnapshot(
                    "error", "The update did not finish. Check the checkout before trying again."
                ))
            values = self._values(result.stdout)
            state, reason = values.get("state"), values.get("reason")
            remote = self._short_sha(values, "remote")
            if result.returncode == 0 and state == "updated":
                return self._set(UpdateSnapshot(
                    state, f"Updated to {remote}. DigitalFrame is restarting now."
                ))
            if result.returncode == 0 and state == "current":
                return self._set(UpdateSnapshot(state, f"Software is already current at {remote}."))
            if reason == "sync":
                message = "Code was updated, but uv sync failed. Run deploy/apply-update.sh from a terminal."
            elif reason == "dirty":
                message = "Local changes appeared after the check; installation was stopped."
            elif reason == "busy":
                message = "Another update operation is already running."
            else:
                message = "The update was stopped safely. Check the checkout from a terminal."
            logger.warning("Update install failed with status %s (%s)", result.returncode, reason)
            return self._set(UpdateSnapshot("error", message))
        finally:
            self._operation_lock.release()
