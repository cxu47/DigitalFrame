import logging

from google.auth.transport.requests import Request
from google.oauth2.credentials import Credentials
from google_auth_oauthlib.flow import InstalledAppFlow
from googleapiclient.discovery import build
from googleapiclient.http import MediaIoBaseDownload

from ..config import (
    GOOGLE_SCOPES,
    GOOGLE_CREDENTIALS_FILE,
    GOOGLE_TOKEN_FILE,
)


logger = logging.getLogger(__name__)


def get_drive_service():
    creds = None

    if GOOGLE_TOKEN_FILE.exists():
        logger.debug("Loading saved Google Drive credentials")
        creds = Credentials.from_authorized_user_file(
            GOOGLE_TOKEN_FILE,
            GOOGLE_SCOPES,
        )

    if not creds or not creds.valid:
        if creds and creds.expired and creds.refresh_token:
            logger.debug("Refreshing Google Drive credentials")
            creds.refresh(Request())
        else:
            logger.info("Starting interactive Google Drive authorization")
            flow = InstalledAppFlow.from_client_secrets_file(
                GOOGLE_CREDENTIALS_FILE,
                GOOGLE_SCOPES,
            )
            creds = flow.run_local_server(port=8080, open_browser=False)

        GOOGLE_TOKEN_FILE.write_text(creds.to_json())
        logger.debug("Saved updated Google Drive credentials")

    logger.debug("Building Google Drive service")
    return build("drive", "v3", credentials=creds)


def _list_children(service, folder_id):
    token = None
    folder_id = folder_id.replace("\\", "\\\\").replace("'", "\\'")
    while True:
        result = service.files().list(
            q=f"'{folder_id}' in parents and trashed = false",
            fields="nextPageToken,incompleteSearch,files(id,name,mimeType,modifiedTime,md5Checksum,size)",
            pageSize=1000,
            pageToken=token,
        ).execute()
        if result.get("incompleteSearch"):
            raise RuntimeError("Drive returned an incomplete folder listing")
        yield from result.get("files", [])
        token = result.get("nextPageToken")
        if not token:
            break


def list_photos(drive_folder_id):
    return [file for file in _list_children(get_drive_service(), drive_folder_id)
            if file["mimeType"].startswith("image/")]


def list_albums(drive_folder_id):
    """Read the complete one-level tree before allowing cache reconciliation."""
    service = get_drive_service()
    albums = []
    for folder in _list_children(service, drive_folder_id):
        if folder["mimeType"] != "application/vnd.google-apps.folder":
            continue
        albums.append({
            "id": folder["id"], "name": folder["name"],
            "photos": [file for file in _list_children(service, folder["id"])
                       if file["mimeType"].startswith("image/")],
        })
    return albums


def download_photo(file_id, destination):
    logger.debug("Starting Google Drive media download")
    service = get_drive_service()

    request = service.files().get_media(fileId=file_id)

    with open(destination, "wb") as file:
        downloader = MediaIoBaseDownload(file, request)

        done = False
        while not done:
            _, done = downloader.next_chunk()

    logger.debug("Google Drive media download completed")
