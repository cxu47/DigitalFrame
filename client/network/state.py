"""Values shared by the unprivileged frame and the board network helper."""

from dataclasses import dataclass, field
import re


class NetworkError(Exception):
    """A deliberately sanitized error that is safe to display."""


def validate_credentials(ssid, password, bssid=None):
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
    if bssid is not None and (not isinstance(bssid, str) or not re.fullmatch(
            r"(?:[0-9a-fA-F]{2}:){5}[0-9a-fA-F]{2}", bssid)):
        raise NetworkError("Choose one of the listed Wi-Fi access points.")


@dataclass(frozen=True)
class NetworkSnapshot:
    state: str = "starting"
    ssid: str = ""
    address: str = ""
    message: str = "Checking Wi-Fi..."
    ap_ssid: str = ""
    ap_password: str = field(default="", repr=False)
    ap_address: str = ""
    access_points: tuple = ()
    revision: int = 0

    @property
    def online(self):
        return self.state == "online"

    @property
    def can_submit(self):
        return self.state == "ap" and any(point.get("supported") for point in self.access_points)

    @property
    def can_refresh(self):
        return self.state == "ap"

    def access_point(self, bssid):
        if not isinstance(bssid, str):
            raise NetworkError("Choose one of the listed Wi-Fi access points.")
        for point in self.access_points:
            if point.get("supported") and point.get("bssid", "").lower() == bssid.lower():
                return point
        raise NetworkError("Choose one of the listed Wi-Fi access points.")

    def banner(self, control_url=None, port=8000):
        if self.online or self.state == "disabled":
            return None
        lines = [self.message]
        if self.ap_ssid and self.state != "starting":
            lines.append(f"Wi-Fi: {self.ap_ssid}  Password: {self.ap_password}")
        if self.state == "connecting":
            lines.append("Wi-Fi setup paused.")
        elif self.state == "ap":
            if control_url:
                lines.append(f"Open: {control_url}")
            elif self.ap_address:
                lines.append(f"Open: http://{self.ap_address}:{port}")
            else:
                lines.append("Control page starting...")
        if self.ap_address and self.state not in {"ap", "starting"} and not control_url:
            lines.append(f"Open when ready: http://{self.ap_address}:{port}")
        return "\n".join(lines)


DISABLED = NetworkSnapshot(state="disabled", message="Wi-Fi setup is not enabled on this device.")
