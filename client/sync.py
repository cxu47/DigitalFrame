from .config import CACHE_DIR, GOOGLE_DRIVE_FOLDER_ID
from .storage.google_drive import list_photos, download_photo


def sync_photos():
    CACHE_DIR.mkdir(parents=True, exist_ok=True)

    try:
        cloud_files = list_photos(GOOGLE_DRIVE_FOLDER_ID)
    except Exception as exc:
        print(f"Sync failed: {exc}")
        return

    for file in cloud_files:
        filename = file["name"]
        file_id = file["id"]

        destination = CACHE_DIR / filename
        temp_destination = CACHE_DIR / f"{filename}.part"

        if destination.exists():
            print(f"Already cached: {filename}")
            continue

        try:
            print(f"Downloading {filename}")

            download_photo(
                file_id,
                temp_destination,
            )

            temp_destination.replace(destination)

        except Exception as exc:
            print(f"Failed to download {filename}: {exc}")

            if temp_destination.exists():
                temp_destination.unlink()


if __name__ == "__main__":
    sync_photos()
