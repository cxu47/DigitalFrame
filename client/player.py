"""Small, dependency-free mpv controller using its supported JSON IPC API."""

from __future__ import annotations

import json
import logging
from pathlib import Path
import re
import socket
import subprocess
from threading import Condition, Lock, Thread
import time


logger = logging.getLogger(__name__)


class MPVError(RuntimeError):
    """mpv could not start or execute a requested operation."""


def _background_commands(version: str):
    """Return black-background commands for mpv's pre/post-0.38 option API."""
    match = re.match(r"^(?:mpv\s+)?v?(\d+)\.(\d+)", version)
    if not match:
        raise MPVError(f"Cannot determine the installed mpv version: {version!r}")
    parsed = tuple(map(int, match.groups()))
    if parsed < (0, 37):
        raise MPVError(f"mpv 0.37 or newer is required; found {version}")
    if parsed < (0, 38):
        return [["set_property", "background", "#000000"]]
    return [
        ["set_property", "background", "color"],
        ["set_property", "background-color", "#000000"],
    ]


def _ass_text(value: str) -> str:
    """Escape user-controlled text before placing it in an ASS overlay."""
    return (value.replace("\\", "\\\\")
                 .replace("{", r"\{")
                 .replace("}", r"\}")
                 .replace("\r\n", r"\N")
                 .replace("\n", r"\N")
                 .replace("\r", r"\N"))


class MPVPlayer:
    """Own one fullscreen mpv process for the lifetime of the slideshow."""

    def __init__(self, executable="mpv", *, command_timeout=5, load_timeout=30):
        self.command_timeout = command_timeout
        self.load_timeout = load_timeout
        self._condition = Condition()
        self._write_lock = Lock()
        self._next_request = 1
        self._replies = {}
        self._loading_id = None
        self._file_loaded = False
        self._load_result = None
        self._closed = False
        parent, child = socket.socketpair()
        try:
            command = [
                executable,
                "--no-config",
                "--idle=yes",
                "--force-window=immediate",
                "--fullscreen=yes",
                "--border=no",
                "--osc=no",
                "--osd-bar=no",
                "--audio=no",
                "--image-display-duration=inf",
                "--keep-open=always",
                "--keepaspect=yes",
                "--panscan=0",
                "--input-default-bindings=no",
                "--terminal=no",
                f"--input-ipc-client=fd://{child.fileno()}",
            ]
            self.process = subprocess.Popen(
                command,
                pass_fds=(child.fileno(),),
                stdin=subprocess.DEVNULL,
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
                close_fds=True,
            )
        except Exception:
            parent.close()
            child.close()
            raise
        child.close()
        self._socket = parent
        self._reader = Thread(target=self._read_messages, name="mpv-ipc", daemon=True)
        self._reader.start()
        try:
            version = self._command(["get_property", "mpv-version"])
            for command in _background_commands(version):
                self._command(command)
            self._command(["define-section", "digitalframe", "ESC quit\nq quit", "force"])
            self._command(["enable-section", "digitalframe", "allow-hide-cursor"])
        except Exception:
            self.close()
            raise
        logger.info("Display initialized with mpv %s", version)

    @property
    def running(self):
        return not self._closed and self.process.poll() is None

    def _read_messages(self):
        try:
            with self._socket.makefile("r", encoding="utf-8", errors="replace") as stream:
                for line in stream:
                    try:
                        message = json.loads(line)
                    except (TypeError, ValueError):
                        logger.warning("Ignoring invalid mpv IPC response")
                        continue
                    with self._condition:
                        if "request_id" in message:
                            self._replies[message["request_id"]] = message
                        event = message.get("event")
                        if event == "start-file":
                            self._loading_id = message.get("playlist_entry_id")
                            self._file_loaded = False
                        elif event == "file-loaded":
                            self._file_loaded = self._loading_id is not None
                        elif event == "playback-restart" and self._file_loaded:
                            # file-loaded can arrive before the video output has
                            # presented the first decoded frame.  Only start the
                            # slideshow interval once playback has really begun.
                            self._load_result = (True, None)
                        elif (event == "end-file" and message.get("reason") == "error"
                              and message.get("playlist_entry_id") == self._loading_id):
                            self._load_result = (False, message.get("file_error") or "mpv could not decode the image")
                        elif event == "shutdown":
                            self._closed = True
                        self._condition.notify_all()
        except OSError:
            pass
        finally:
            with self._condition:
                self._closed = True
                self._condition.notify_all()

    def _command(self, command):
        with self._condition:
            if not self.running:
                raise MPVError("mpv exited unexpectedly")
            request_id = self._next_request
            self._next_request += 1
        payload = json.dumps({"command": command, "request_id": request_id},
                             ensure_ascii=False, separators=(",", ":")) + "\n"
        try:
            with self._write_lock:
                self._socket.sendall(payload.encode("utf-8"))
        except OSError as exc:
            raise MPVError(f"Cannot communicate with mpv: {exc}") from exc
        deadline = time.monotonic() + self.command_timeout
        with self._condition:
            while request_id not in self._replies and self.running:
                remaining = deadline - time.monotonic()
                if remaining <= 0:
                    raise MPVError("mpv did not answer an IPC command")
                self._condition.wait(remaining)
            if request_id not in self._replies:
                raise MPVError("mpv exited while handling an IPC command")
            reply = self._replies.pop(request_id)
        if reply.get("error") != "success":
            raise MPVError(f"mpv command failed: {reply.get('error', 'unknown error')}")
        return reply.get("data")

    def load(self, path: Path):
        with self._condition:
            self._load_result = None
            self._loading_id = None
            self._file_loaded = False
        self.clear_overlay(2)
        self._command(["loadfile", str(path.resolve()), "replace"])
        deadline = time.monotonic() + self.load_timeout
        with self._condition:
            while self._load_result is None and self.running:
                remaining = deadline - time.monotonic()
                if remaining <= 0:
                    raise MPVError("mpv timed out before displaying the image")
                self._condition.wait(remaining)
            if self._load_result is None:
                raise MPVError("mpv exited while loading the image")
            success, error = self._load_result
        if not success:
            raise MPVError(error)

    def stop(self):
        self._command(["stop"])

    def set_overlay(self, overlay_id: int, text: str, *, color="white", position="top"):
        color_tag = r"\1c&H0000FF&" if color == "red" else r"\1c&HFFFFFF&"
        if position == "center":
            layout = r"\an5\pos(640,360)\fs36\q2"
        else:
            layout = r"\an7\pos(12,12)\fs28\q2"
        data = "{" + layout + color_tag + r"\3c&H000000&\bord4}" + _ass_text(text)
        self._command({
            "name": "osd-overlay",
            "id": overlay_id,
            "format": "ass-events",
            "data": data,
            "res_x": 1280,
            "res_y": 720,
            "z": overlay_id,
        })

    def clear_overlay(self, overlay_id: int):
        if self.running:
            self._command({
                "name": "osd-overlay",
                "id": overlay_id,
                # An empty ASS overlay clears the text on mpv 0.37 and newer.
                # mpv 0.37 rejects the documented ``format=none`` form when
                # the command is sent with named JSON IPC arguments.
                "format": "ass-events",
                "data": "",
                "res_x": 1280,
                "res_y": 720,
                "z": overlay_id,
            })

    def wait(self, milliseconds: int):
        time.sleep(milliseconds / 1000)

    def close(self):
        if getattr(self, "process", None) is None:
            return
        if self.running:
            try:
                self._command(["quit"])
            except MPVError:
                pass
        try:
            self.process.wait(timeout=5)
        except subprocess.TimeoutExpired:
            self.process.terminate()
            try:
                self.process.wait(timeout=2)
            except subprocess.TimeoutExpired:
                self.process.kill()
                self.process.wait(timeout=2)
        self._closed = True
        try:
            self._socket.close()
        except OSError:
            pass
        self._reader.join(timeout=1)

    def __enter__(self):
        return self

    def __exit__(self, *exc_info):
        self.close()
