from pathlib import Path
import httpx

SERVER_URL = "http://127.0.0.1:8000"
CACHE_DIR = Path("client/cache")


def get_photo_names():
    response = httpx.get(f"{SERVER_URL}/photos")
    response.raise_for_status()
    return response.json()["photos"]


def download_photo(filename):
    response = httpx.get(f"{SERVER_URL}/photos/{filename}")
    response.raise_for_status()

    destination = CACHE_DIR / filename
    destination.write_bytes(response.content)


def sync_photos():
    CACHE_DIR.mkdir(parents=True, exist_ok=True)

    server_photos = get_photo_names()

    for filename in server_photos:
        destination = CACHE_DIR / filename

        if not destination.exists():
            print(f"Downloading {filename}")
            download_photo(filename)
        else:
            print(f"Already cached: {filename}")


if __name__ == "__main__":
    sync_photos()
