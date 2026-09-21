"""Read and validate only the configuration needed by the requested command."""

import math
import os
from pathlib import Path

from dotenv import load_dotenv
from .settings import parse_display_seconds, parse_selected_months

CLIENT_DIR = Path(__file__).resolve().parent
ENV_FILE = CLIENT_DIR.parent / ".env"
load_dotenv(ENV_FILE)


def required_env(name):
    value = os.getenv(name, "").strip()
    if not value:
        raise ValueError(f"Missing required configuration: {name}. See .env.example.")
    return value


def seconds_from_env(name, default=None):
    try:
        value = float(os.getenv(name, default) if default is not None else required_env(name))
        if not math.isfinite(value) or value < 0.001:
            raise ValueError
        return value
    except (TypeError, ValueError):
        raise ValueError(f"{name} must be a finite number of at least 0.001 seconds.") from None


def bounded_integer_from_env(name, default, minimum, maximum):
    try:
        value = int(os.getenv(name, default))
        if not minimum <= value <= maximum:
            raise ValueError
        return value
    except (TypeError, ValueError):
        raise ValueError(f"{name} must be a whole number from {minimum} to {maximum}.") from None


def __getattr__(name):
    # Module attributes remain convenient for each workflow, without requiring
    # Cloud credentials are only needed by sync, not cache-only playback or settings.
    if name == "WIFI_SETUP_ENABLED":
        value = os.getenv(name, "false").strip().lower()
        if value not in {"true", "false", "1", "0"}:
            raise ValueError("WIFI_SETUP_ENABLED must be true or false.")
        return value in {"true", "1"}
    if name == "WIFI_SOCKET":
        return os.getenv(name, "/run/digitalframe-network/control.sock")
    if name == "CACHE_DIR":
        return CLIENT_DIR / required_env("CACHE_FOLDER")
    if name == "DISPLAY_SECONDS":
        try:
            return parse_display_seconds(os.getenv(name, "5"))
        except ValueError:
            raise ValueError("DISPLAY_SECONDS must be a positive integer.") from None
    if name == "SELECTED_FOLDER":
        return os.getenv(name, "") or None
    if name == "SELECTED_MONTHS":
        try:
            return parse_selected_months(os.getenv(name, ""))
        except ValueError:
            raise ValueError(
                "SELECTED_MONTHS must be comma-separated YYYY-MM values.") from None
    if name == "VIEW_MODE":
        value = os.getenv(name, "folder").strip().lower()
        if value not in {"folder", "months"}:
            raise ValueError("VIEW_MODE must be folder or months.")
        return value
    if name in {"CACHE_MAX_WIDTH", "CACHE_MAX_HEIGHT"}:
        return bounded_integer_from_env(name, "1600" if name.endswith("WIDTH") else "900", 1, 16384)
    if name == "MAX_SOURCE_MEGABYTES":
        return bounded_integer_from_env(name, "5", 1, 1024)
    if name == "MAX_SOURCE_MEGAPIXELS":
        return bounded_integer_from_env(name, "50", 1, 1000)
    if name in {"HDMI_MAX_WIDTH", "HDMI_MAX_HEIGHT"}:
        return bounded_integer_from_env(name, "1920" if name.endswith("WIDTH") else "1080", 1, 16384)
    if name == "HDMI_PREFERRED_HZ":
        return bounded_integer_from_env(name, "30", 1, 240)
    if name in {"OTHER_IMAGE_QUALITY", "IPHONE_JPEG_QUALITY"}:
        return bounded_integer_from_env(
            name, "75" if name == "IPHONE_JPEG_QUALITY" else "85", 1, 95)
    if name in {"IDLE_SECONDS", "SYNC_INTERVAL"}:
        return seconds_from_env(name)
    if name == "NETWORK_TIMEOUT":
        return seconds_from_env(name, "10")
    if name == "CONTROL_HOST":
        value = os.getenv(name, "0.0.0.0").strip()
        if not value:
            raise ValueError("CONTROL_HOST must not be empty.")
        return value
    if name == "CONTROL_PORT":
        try:
            value = parse_display_seconds(os.getenv(name, "8000"))
            if value > 65535:
                raise ValueError
            return value
        except ValueError:
            raise ValueError("CONTROL_PORT must be an integer from 1 to 65535.") from None
    if name == "CONTROL_URL_DISPLAY_SECONDS":
        value = os.getenv(name, "30").strip()
        if not value.isascii() or not value.isdigit():
            raise ValueError(f"{name} must be a nonnegative integer.")
        return int(value)
    if name == "LOG_LEVEL":
        return os.getenv(name, "INFO")
    if name == "OSS_CREDENTIALS_FILE":
        filename = os.getenv(name, "oss.env").strip()
        path = Path(filename)
        if (not filename or path.is_absolute()
                or len(path.parts) != 1 or path.name in {".", ".."}):
            raise ValueError("OSS_CREDENTIALS_FILE must be a filename inside SECRETS_FOLDER.")
        return CLIENT_DIR / required_env("SECRETS_FOLDER") / path
    if name == "GOOGLE_SCOPES":
        return ["https://www.googleapis.com/auth/drive.readonly"]
    if name == "GOOGLE_DRIVE_FOLDER_ID":
        return required_env(name)
    if name in {"GOOGLE_CREDENTIALS_FILE", "GOOGLE_TOKEN_FILE"}:
        return CLIENT_DIR / required_env("SECRETS_FOLDER") / required_env(name)
    raise AttributeError(name)
