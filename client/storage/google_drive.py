import logging
from functools import partial

import httplib2
from google_auth_httplib2 import AuthorizedHttp

from google.auth.transport.requests import Request
from google.oauth2.credentials import Credentials
from google_auth_oauthlib.flow import InstalledAppFlow
from googleapiclient.discovery import build
from googleapiclient.http import MediaIoBaseDownload

from ..config import (
    GOOGLE_SCOPES,
    GOOGLE_CREDENTIALS_FILE,
    GOOGLE_TOKEN_FILE,
    NETWORK_TIMEOUT,
)
from ..cache import supported_photo
from ..cancellation import check_cancelled


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
            creds.refresh(partial(Request(), timeout=NETWORK_TIMEOUT))
        else:
            logger.info("Starting interactive Google Drive authorization")
            flow = InstalledAppFlow.from_client_secrets_file(
                GOOGLE_CREDENTIALS_FILE,
                GOOGLE_SCOPES,
            )
            flow.oauth2session.request = partial(flow.oauth2session.request, timeout=NETWORK_TIMEOUT)
            creds = flow.run_local_server(port=8080, open_browser=False, timeout_seconds=60)

        GOOGLE_TOKEN_FILE.parent.mkdir(parents=True, exist_ok=True)
        temporary_token = GOOGLE_TOKEN_FILE.with_name(GOOGLE_TOKEN_FILE.name + ".part")
        temporary_token.write_text(creds.to_json())
        temporary_token.replace(GOOGLE_TOKEN_FILE)
        logger.debug("Saved updated Google Drive credentials")

    logger.debug("Building Google Drive service")
    return build("drive", "v3", http=AuthorizedHttp(creds, http=httplib2.Http(timeout=NETWORK_TIMEOUT)))


def _list_children(service, folder_id, stop_event=None):
    token = None
    folder_id = folder_id.replace("\\", "\\\\").replace("'", "\\'")
    while True:
        check_cancelled(stop_event)
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


def list_albums(drive_folder_id, *, service=None, stop_event=None):
    """Read the complete one-level tree before allowing cache reconciliation."""
    service = service if service is not None else get_drive_service()
    albums = []
    for folder in _list_children(service, drive_folder_id, stop_event):
        if folder["mimeType"] != "application/vnd.google-apps.folder":
            continue
        albums.append({
            "id": folder["id"], "name": folder["name"],
            "photos": [file for file in _list_children(service, folder["id"], stop_event)
                       if file["mimeType"].startswith("image/") and supported_photo(file["name"])],
        })
    return albums


def download_photo(file_id, destination, *, service=None, stop_event=None):
    logger.debug("Starting Google Drive media download")
    service = service if service is not None else get_drive_service()

    request = service.files().get_media(fileId=file_id)

    with open(destination, "wb") as file:
        downloader = MediaIoBaseDownload(file, request, chunksize=1024 * 1024)

        done = False
        while not done:
            check_cancelled(stop_event)
            _, done = downloader.next_chunk()

    logger.debug("Google Drive media download completed")
