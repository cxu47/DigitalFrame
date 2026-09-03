import logging

import pygame
from .config import CACHE_DIR, DISPLAY_SECONDS, IDLE_SECONDS
from .logging_config import configure_logging
from PIL import ExifTags, Image, ImageOps
from pillow_heif import register_heif_opener
register_heif_opener()


logger = logging.getLogger(__name__)

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

def get_cached_photos():
    supported = {".jpg", ".jpeg", ".png", ".webp", ".heic", ".heif"}

    return sorted(
        path
        for path in CACHE_DIR.iterdir()
        if path.is_file() and path.suffix.lower() in supported
    )

def show_first_photo(): #only for testing. later replaced by the following two functions.
    photos = get_cached_photos()

    if not photos:
        logger.info("No cached photos available")
        return

    pygame.init()

    screen = pygame.display.set_mode((800, 600))
    pygame.display.set_caption("Digital Frame")

    image = pygame.image.load(photos[0])

    screen_width, screen_height = screen.get_size()
    image_width, image_height = image.get_size()

    scale = min(
        screen_width / image_width,
        screen_height / image_height,
    )

    new_width = int(image_width * scale)
    new_height = int(image_height * scale)

    image = pygame.transform.smoothscale(
        image,
        (new_width, new_height),
    )

    x = (screen_width - new_width) // 2
    y = (screen_height - new_height) // 2

    screen.fill("black")
    screen.blit(image, (x, y))
    pygame.display.flip()

    running = True

    while running:
        running = handle_events()


    pygame.quit()

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

def show_slideshow():
    pygame.init()

    screen = pygame.display.set_mode((800, 600))
    pygame.display.set_caption("Digital Frame")

    logger.info("Slideshow started")
    running = True
    waiting_for_photos = False

    try:
        while running:
            photos = get_cached_photos()
            if not photos:
                if not waiting_for_photos:
                    logger.info("No cached photos available; waiting")
                    waiting_for_photos = True

                display_message(
                    screen,
                    "No cached photos available."
                )

                running = handle_events()

                pygame.time.wait(int(IDLE_SECONDS * 1000))
                continue

            if waiting_for_photos:
                logger.info(
                    "Cached photos available; resuming slideshow"
                )
                waiting_for_photos = False

            for photo_path in photos:
                success = display_photo(screen, photo_path)
                if not success:
                    continue

                start_time = pygame.time.get_ticks()

                while (
                    pygame.time.get_ticks() - start_time
                    < int(DISPLAY_SECONDS * 1000)
                ):
                    running = handle_events()

                    if not running:
                        break

                    pygame.time.wait(int(IDLE_SECONDS * 1000))

                if not running:
                    break

    finally:
        pygame.quit()
        logger.info("Slideshow stopped")

if __name__ == "__main__":
    configure_logging()
    show_slideshow()
