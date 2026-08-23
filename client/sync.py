from pathlib import Path
import httpx
from .config import CACHE_DIR, SERVER_URL, TIMEOUT, GOOGLE_DRIVE_FOLDER_ID
from .storage.google_drive import list_photos

'''
fast api get, download photos, synch photos
'''
#def get_photo_names():
#    response = httpx.get(f"{SERVER_URL}/photos", timeout=TIMEOUT,)
#    response.raise_for_status()
#    return response.json()["photos"]
#
#def download_photo(filename):
#    response = httpx.get(f"{SERVER_URL}/photos/{filename}", timeout=TIMEOUT,)
#    response.raise_for_status()
#
#    destination = CACHE_DIR / filename
#    temp_destination = CACHE_DIR / f"{filename}.part"
#
#    temp_destination.write_bytes(response.content)
#    temp_destination.replace(destination)
#
#def sync_photos_fastAPI(): 
#    CACHE_DIR.mkdir(parents=True, exist_ok=True)
#
#    try:
#        server_photos = get_photo_names()
#    except httpx.HTTPError as exc:
#        print(f"Sync failed: {exc}")
#        return
#
#    for filename in server_photos:
#        destination = CACHE_DIR / filename
#
#        if not destination.exists():
#            print(f"Downloading {filename}")
#            download_photo(filename)
#        else:
#            print(f"Already cached: {filename}")

'''
sync photos using google
'''
def sync_photos():
    cloud_files = list_photos(GOOGLE_DRIVE_FOLDER_ID)

    for file in cloud_files:
        print(file["name"])

if __name__ == "__main__":
    sync_photos()
