import os
from pathlib import Path
from dotenv import load_dotenv

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
DISPLAY_SECONDS = seconds_from_env("DISPLAY_SECONDS")
IDLE_SECONDS = seconds_from_env("IDLE_SECONDS")

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
