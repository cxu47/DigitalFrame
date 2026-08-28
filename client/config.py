import os
from pathlib import Path
from dotenv import load_dotenv

CLIENT_DIR = Path(__file__).resolve().parent
load_dotenv(CLIENT_DIR.parent / ".env")
CACHE_DIR = CLIENT_DIR / os.getenv("CACHE_FOLDER")

#slideshow
DISPLAY_SECONDS =  float(os.getenv("DISPLAY_SECONDS"))
IDLE_SECONDS =  float(os.getenv("IDLE_SECONDS"))

#sync
SYNC_INTERVAL = float(os.getenv("SYNC_INTERVAL")) 

# google configs (inside client/)
GOOGLE_SCOPES = ["https://www.googleapis.com/auth/drive.readonly"]
GOOGLE_DRIVE_FOLDER_ID = os.getenv("GOOGLE_DRIVE_FOLDER_ID")
GOOGLE_CREDENTIALS_FILE = Path(CLIENT_DIR / os.getenv("SECRETS_FOLDER") / os.getenv("GOOGLE_CREDENTIALS_FILE"))
GOOGLE_TOKEN_FILE = Path(CLIENT_DIR / os.getenv("SECRETS_FOLDER") / os.getenv("GOOGLE_TOKEN_FILE"))
