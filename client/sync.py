from pathlib import Path
import httpx

SERVER_URL = "http://127.0.0.1:8000"
CACHE_DIR = Path("client/cache")
TIMEOUT = 60

def get_photo_names():
    response = httpx.get(f"{SERVER_URL}/photos", timeout=TIMEOUT,)
    response.raise_for_status()
    return response.json()["photos"]

def download_photo(filename):
    response = httpx.get(f"{SERVER_URL}/photos/{filename}", timeout=TIMEOUT,)
    response.raise_for_status()

    destination = CACHE_DIR / filename
    temp_destination = CACHE_DIR / f"{filename}.part"

    temp_destination.write_bytes(response.content)
    temp_destination.replace(destination)

def sync_photos():
    CACHE_DIR.mkdir(parents=True, exist_ok=True)

    try:
        server_photos = get_photo_names()
    except httpx.HTTPError as exc:
        print(f"Sync failed: {exc}")
        return

    for filename in server_photos:
        destination = CACHE_DIR / filename

        if not destination.exists():
            print(f"Downloading {filename}")
            download_photo(filename)
        else:
            print(f"Already cached: {filename}")

if __name__ == "__main__":
    sync_photos()
