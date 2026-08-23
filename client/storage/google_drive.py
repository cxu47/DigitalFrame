from pathlib import Path

from google.auth.transport.requests import Request
from google.oauth2.credentials import Credentials
from google_auth_oauthlib.flow import InstalledAppFlow
from googleapiclient.discovery import build
from ..config import GOOGLE_SCOPES, GOOGLE_CREDENTIALS_FILE, GOOGLE_TOKEN_FILE



def get_drive_service():
    creds = None

    if GOOGLE_TOKEN_FILE.exists():
        creds = Credentials.from_authorized_user_file(
            GOOGLE_TOKEN_FILE,
            GOOGLE_SCOPES,
        )

    if not creds or not creds.valid:
        if creds and creds.expired and creds.refresh_token:
            creds.refresh(Request())
        else:
            flow = InstalledAppFlow.from_client_secrets_file(
                GOOGLE_CREDENTIALS_FILE,
                GOOGLE_SCOPES,
            )
            creds = flow.run_local_server(port=0)

        GOOGLE_TOKEN_FILE.write_text(creds.to_json())

    return build("drive", "v3", credentials=creds)

def list_photos(driver_foler):
    service = get_drive_service()

    result = service.files().list(
        q=f"'{driver_foler}' in parents and trashed = false",
        fields="files(id, name, mimeType, modifiedTime)",
    ).execute()

    return result.get("files", [])
