import os
from pathlib import Path
from dotenv import load_dotenv
from .settings import parse_display_seconds

CLIENT_DIR = Path(__file__).resolve().parent
load_dotenv(CLIENT_DIR.parent / ".env")


def required_env(name):
    value = os.getenv(name)
    if value is None:
        raise ValueError(f"Missing required configuration: {name}. See .env.example.")
    return value


def seconds_from_env(name):
    value = required_env(name)
    try:
        return float(value)
    except ValueError:
        raise ValueError(f"{name} must be a number of seconds.") from None


# Relative paths are resolved from client/; absolute paths remain absolute.
CACHE_DIR = CLIENT_DIR / required_env("CACHE_FOLDER")

# Slideshow
try:
    DISPLAY_SECONDS = parse_display_seconds(required_env("DISPLAY_SECONDS"))
except ValueError as exc:
    raise ValueError(f"DISPLAY_SECONDS: {exc}") from None
IDLE_SECONDS = seconds_from_env("IDLE_SECONDS")

# The browser on another device uses the frame's Wi-Fi IP, not this bind address.
CONTROL_HOST = os.getenv("CONTROL_HOST", "0.0.0.0").strip()
if not CONTROL_HOST:
    raise ValueError("CONTROL_HOST must not be empty.")
try:
    CONTROL_PORT = parse_display_seconds(os.getenv("CONTROL_PORT", "8000"))
    if CONTROL_PORT > 65535:
        raise ValueError
except ValueError:
    raise ValueError("CONTROL_PORT must be an integer from 1 to 65535.") from None

# Show the access URL once when the slideshow opens; zero disables the banner.
try:
    _url_seconds = os.getenv("CONTROL_URL_DISPLAY_SECONDS", "30").strip()
    if not _url_seconds.isascii() or not _url_seconds.isdigit():
        raise ValueError
    CONTROL_URL_DISPLAY_SECONDS = int(_url_seconds)
except ValueError:
    raise ValueError("CONTROL_URL_DISPLAY_SECONDS must be a nonnegative integer.") from None

# Sync
SYNC_INTERVAL = seconds_from_env("SYNC_INTERVAL")

# Logging
LOG_LEVEL = os.getenv("LOG_LEVEL", "INFO")

# Google credentials and token filenames are relative to SECRETS_FOLDER.
GOOGLE_SCOPES = ["https://www.googleapis.com/auth/drive.readonly"]
# Only Drive sync needs this value; a cache-only slideshow can run without it.
GOOGLE_DRIVE_FOLDER_ID = os.getenv("GOOGLE_DRIVE_FOLDER_ID")
GOOGLE_CREDENTIALS_FILE = (
    CLIENT_DIR / required_env("SECRETS_FOLDER") / required_env("GOOGLE_CREDENTIALS_FILE")
)
GOOGLE_TOKEN_FILE = (
    CLIENT_DIR / required_env("SECRETS_FOLDER") / required_env("GOOGLE_TOKEN_FILE")
)
