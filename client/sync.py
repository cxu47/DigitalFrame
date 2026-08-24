from pathlib import Path
import httpx
from .config import CACHE_DIR, SERVER_URL, TIMEOUT, GOOGLE_DRIVE_FOLDER_ID
from .storage.google_drive import list_photos

'''
sync photos using google
'''
def sync_photos():
    cloud_files = list_photos(GOOGLE_DRIVE_FOLDER_ID)

    for file in cloud_files:
        print(file["name"])

if __name__ == "__main__":
    sync_photos()
