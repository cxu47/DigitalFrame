from pathlib import Path

# fastAPI server
SERVER_URL = "http://127.0.0.1:8000"
TIMEOUT = 60
SYNC_INTERVAL = 1 #60 

# client configs
CLIENT_DIR = Path(__file__).resolve().parent
CACHE_DIR = CLIENT_DIR / "cache"
DISPLAY_SECONDS = 5
IDLE_SECONDS = 0.5

# google configs (inside client/)
GOOGLE_SCOPES = ["https://www.googleapis.com/auth/drive.readonly"]
GOOGLE_DRIVE_FOLDER_ID = "1PCx8gffDxNx9AdDQjKPgpNyXBa74pxM1"
GOOGLE_CREDENTIALS_FILE = CLIENT_DIR / "secrets" / "google_credentials.json"
GOOGLE_TOKEN_FILE =  CLIENT_DIR / "secrets" / "google_token.json"
