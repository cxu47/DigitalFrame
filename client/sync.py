import logging

from .config import CACHE_DIR, GOOGLE_DRIVE_FOLDER_ID
from .logging_config import configure_logging
from .storage.google_drive import list_photos, download_photo


logger = logging.getLogger(__name__)


def sync_photos():
    logger.debug("Photo sync started")
    CACHE_DIR.mkdir(parents=True, exist_ok=True)

    try:
        cloud_files = list_photos(GOOGLE_DRIVE_FOLDER_ID)
    except Exception:
        logger.exception(
            "Photo sync failed while listing Google Drive photos"
        )
        return

    downloaded_count = 0
    cached_count = 0
    failed_count = 0

    for file in cloud_files:
        filename = file["name"]
        file_id = file["id"]

        destination = CACHE_DIR / filename
        temp_destination = CACHE_DIR / f"{filename}.part"

        if destination.exists():
            cached_count += 1
            logger.debug("Already cached: %s", filename)
            continue

        try:
            logger.info("Downloading %s", filename)

            download_photo(
                file_id,
                temp_destination,
            )

            temp_destination.replace(destination)
            downloaded_count += 1
            logger.info("Downloaded %s", filename)

        except Exception:
            failed_count += 1
            logger.exception("Failed to download %s", filename)

            if temp_destination.exists():
                temp_destination.unlink()

    completion_message = (
        "Photo sync completed with changes"
        if downloaded_count
        else "Photo sync completed with no changes"
    )
    completion_logger = logger.info if downloaded_count else logger.debug
    completion_logger(
        "%s: %d remote, %d downloaded, %d cached, %d failed",
        completion_message,
        len(cloud_files),
        downloaded_count,
        cached_count,
        failed_count,
    )


if __name__ == "__main__":
    configure_logging()
    sync_photos()
