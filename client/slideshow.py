import logging
from collections import deque
from queue import Empty

import pygame
from .config import CACHE_DIR, DISPLAY_SECONDS, IDLE_SECONDS
from .settings import RuntimeSettings
from .overlay import SlideshowOverlay
from PIL import ExifTags, Image, ImageOps
from pillow_heif import register_heif_opener
register_heif_opener()


logger = logging.getLogger(__name__)
SUPPORTED_PHOTO_SUFFIXES = {".jpg", ".jpeg", ".png", ".webp", ".heic", ".heif"}

def handle_events():
    for event in pygame.event.get():
        if event.type == pygame.QUIT:
            return False

        if event.type == pygame.KEYDOWN and event.key == pygame.K_ESCAPE:
            return False

    return True

def display_message(screen, message):
    screen.fill("black")

    font = pygame.font.Font(None, 36)
    text = font.render(message, True, "white")

    text_rect = text.get_rect(
        center=screen.get_rect().center
    )

    screen.blit(text, text_rect)
    pygame.display.flip()

def get_cached_folders():
    if not CACHE_DIR.exists():
        return []
    return sorted(path.name for path in CACHE_DIR.iterdir()
                  if not path.name.startswith(".") and not path.is_symlink() and path.is_dir())


def get_cached_photos():
    return sorted(
        path
        for folder in get_cached_folders()
        for path in (CACHE_DIR / folder).glob("*")
        if not path.is_symlink() and path.is_file() and path.suffix.lower() in SUPPORTED_PHOTO_SUFFIXES
    )

def prioritize_new_photos(photos, new_photos, accepts=lambda photo: True):
    """Check for completed downloads between photos, retaining the cycle's place."""
    remaining = deque(photos)
    shown = set()
    while True:
        if new_photos is not None:
            try:
                photo = new_photos.get_nowait()
            except Empty:
                pass
            else:
                if (photo.suffix.lower() in SUPPORTED_PHOTO_SUFFIXES
                        and photo not in shown and accepts(photo)):
                    shown.add(photo)
                    yield photo
                continue
        if not remaining:
            return
        photo = remaining.popleft()
        if photo not in shown and accepts(photo):
            shown.add(photo)
            yield photo

def display_photo(screen, photo_path):
    image = None
    pixel_buffer = None

    try:
        with Image.open(photo_path) as img:
            screen_width, screen_height = screen.get_size()

            orientation = img.getexif().get(ExifTags.Base.Orientation, 1)
            swaps_dimensions = orientation in {5, 6, 7, 8}
            image_width, image_height = img.size
            if swaps_dimensions:
                image_width, image_height = image_height, image_width

            scale = min(
                screen_width / image_width,
                screen_height / image_height,
            )

            new_size = (
                max(1, int(image_width * scale)),
                max(1, int(image_height * scale)),
            )

            # JPEG decoders can use this hint to avoid decoding more pixels
            # than the display needs. Other formats safely ignore it.
            draft_size = (
                (new_size[1], new_size[0])
                if swaps_dimensions
                else new_size
            )
            img.draft("RGB", draft_size)
            ImageOps.exif_transpose(img, in_place=True)

            # Resize before creating the Pygame surface so only the small,
            # display-sized pixel buffer is copied into Pygame.
            resized_image = img
            if scale < 1:
                img.thumbnail(new_size, Image.Resampling.LANCZOS)
            elif img.size != new_size:
                resized_image = img.resize(
                    new_size,
                    Image.Resampling.LANCZOS,
                )

            try:
                display_image = (
                    resized_image
                    if resized_image.mode == "RGB"
                    else resized_image.convert("RGB")
                )
                try:
                    pixel_buffer = display_image.tobytes()
                    image = pygame.image.frombytes(
                        pixel_buffer,
                        display_image.size,
                        "RGB",
                    )
                finally:
                    if display_image is not resized_image:
                        display_image.close()
            finally:
                if resized_image is not img:
                    resized_image.close()

        # frombytes has copied the pixels, so the temporary byte buffer can be
        # released before the photo remains on screen for DISPLAY_SECONDS.
        pixel_buffer = None

    except (pygame.error, FileNotFoundError, OSError) as exc:
        logger.warning(
            "Skipping unavailable image %s: %s",
            photo_path.name,
            exc,
        )
        return False

    image_width, image_height = image.get_size()
    x = (screen_width - image_width) // 2
    y = (screen_height - image_height) // 2

    screen.fill("black")
    screen.blit(image, (x, y))
    pygame.display.flip()
    logger.debug("Displayed photo: %s", photo_path.name)

    # The display surface owns its copied pixels after blit/flip; keeping this
    # source surface alive would retain the previous photo's buffer.
    image = None
    return True

def show_slideshow(settings=None, *, check_running=lambda: None,
                   control_url=None, url_display_seconds=30, new_photos=None):
    if settings is None:
        settings = RuntimeSettings(DISPLAY_SECONDS, folders=get_cached_folders)
    pygame.init()

    logger.info("Slideshow started")
    running = True
    waiting_for_photos = False

    try:
        # Use the selected display's current resolution. A fixed 4:3 mode can
        # be stretched by the display to widescreen even when photos are fitted
        # proportionally within the Pygame surface.
        screen = pygame.display.set_mode((0, 0), pygame.FULLSCREEN)
        logger.info(
            "Display initialized: backend=%s, surface=%s, window=%s",
            pygame.display.get_driver(),
            screen.get_size(),
            pygame.display.get_window_size(),
        )
        pygame.display.set_caption("Digital Frame")
        screen.fill("black")
        pygame.display.flip()
        overlay = SlideshowOverlay(screen, control_url, url_display_seconds)
        overlay.new_frame()
        observed_revision = 0

        def refresh_overlay():
            nonlocal observed_revision
            message, revision = settings.notification_snapshot()
            if revision != observed_revision:
                overlay.show_message(message, 15)
                observed_revision = revision
            overlay.update()

        while running:
            check_running()
            refresh_overlay()
            selected_folder = settings.selected_folder
            photos = get_cached_photos()
            if selected_folder is not None:
                photos = [photo for photo in photos if photo.parent.name == selected_folder]
            if not photos:
                if not waiting_for_photos:
                    logger.info("No cached photos available; waiting")
                    waiting_for_photos = True

                display_message(
                    screen,
                    "No cached photos available."
                )
                overlay.new_frame()

                running = handle_events()

                overlay.wait(int(IDLE_SECONDS * 1000))
                continue

            if waiting_for_photos:
                logger.info(
                    "Cached photos available; resuming slideshow"
                )
                waiting_for_photos = False

            def accepts(photo):
                return (photo.parent.parent == CACHE_DIR and photo.is_file()
                        and (selected_folder is None or photo.parent.name == selected_folder))

            rotation = prioritize_new_photos(photos, new_photos, accepts=accepts)
            while True:
                check_running()
                refresh_overlay()
                if settings.selected_folder != selected_folder:
                    break
                try:
                    photo_path = next(rotation)
                except StopIteration:
                    break
                if not handle_events():
                    running = False
                    break
                success = display_photo(screen, photo_path)
                if not success:
                    continue

                start_time = pygame.time.get_ticks()
                duration_ms = settings.display_seconds * 1000
                overlay.new_frame()

                while (
                    pygame.time.get_ticks() - start_time
                    < duration_ms
                ):
                    check_running()
                    refresh_overlay()
                    running = handle_events()

                    if not running:
                        break

                    overlay.wait(int(IDLE_SECONDS * 1000))

                if not running:
                    break

    finally:
        pygame.quit()
        logger.info("Slideshow stopped")

if __name__ == "__main__":
    from .runtime import main

    main()
