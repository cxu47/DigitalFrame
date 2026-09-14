"""Values shared by the unprivileged frame and the board network helper."""

from dataclasses import dataclass, field
import re


class NetworkError(Exception):
    """A deliberately sanitized error that is safe to display."""


def validate_credentials(ssid, password):
    try:
        ssid_bytes = ssid.encode("utf-8") if isinstance(ssid, str) else b""
    except UnicodeError:
        ssid_bytes = b""
    if not 1 <= len(ssid_bytes) <= 32 or any(ord(c) < 32 for c in ssid):
        raise NetworkError("Enter a Wi-Fi SSID of 1–32 bytes without control characters.")
    if not isinstance(password, str) or not (
        8 <= len(password) <= 63 and all(32 <= ord(c) <= 126 for c in password)
        or re.fullmatch(r"[0-9a-fA-F]{64}", password)
    ):
        raise NetworkError("Enter a WPA2 password of 8–63 printable ASCII characters or a 64-digit hexadecimal key.")


@dataclass(frozen=True)
class NetworkSnapshot:
    state: str = "starting"
    ssid: str = ""
    address: str = ""
    message: str = "Checking the board connection. Cached playback continues."
    ap_ssid: str = ""
    ap_password: str = field(default="", repr=False)
    ap_address: str = ""
    revision: int = 0

    @property
    def online(self):
        return self.state == "online"

    @property
    def can_submit(self):
        return self.state == "ap"

    def banner(self, control_url=None, port=8000):
        if self.online or self.state == "disabled":
            return None
        lines = [self.message]
        if self.ap_ssid:
            lines += [f"Connect to Wi-Fi: {self.ap_ssid}", f"Setup password: {self.ap_password}"]
        if self.state == "connecting":
            lines.append("Setup hotspot temporarily unavailable during the attempt.")
        elif self.state == "ap":
            lines.append(f"Open: {control_url}" if control_url else "Control panel is starting or unavailable.")
            lines.append("Enter your home Wi-Fi details to reconnect.")
        if self.ap_address and (self.state != "ap" or not control_url):
            lines.append(f"Setup URL when available: http://{self.ap_address}:{port}")
        return "\n".join(lines)


DISABLED = NetworkSnapshot(state="disabled", message="Wi-Fi setup is not enabled on this device.")
