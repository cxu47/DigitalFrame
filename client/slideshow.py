import logging
import time
from collections import deque
from queue import Empty

import pygame
from .config import CACHE_DIR, DISPLAY_SECONDS, IDLE_SECONDS
from .settings import RuntimeSettings
from .overlay import SlideshowOverlay
from .cache import SUPPORTED_PHOTO_SUFFIXES, cached_folders, cached_photos
from .preload import PhotoChanged, PhotoLoader, PreparedPhoto, file_signature
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

def get_cached_folders():
    return cached_folders(CACHE_DIR)


def get_cached_photos():
    return cached_photos(CACHE_DIR)

def prepare_photo(photo_path, screen_size):
    """Decode/resize on a worker; return only display-sized RGB pixels."""
    signature = file_signature(photo_path)
    with Image.open(photo_path) as img:
        screen_width, screen_height = screen_size
        orientation = img.getexif().get(ExifTags.Base.Orientation, 1)
        swaps_dimensions = orientation in {5, 6, 7, 8}
        image_width, image_height = img.size
        if swaps_dimensions:
            image_width, image_height = image_height, image_width
        scale = min(screen_width / image_width, screen_height / image_height)
        new_size = (max(1, int(image_width * scale)), max(1, int(image_height * scale)))
        img.draft("RGB", (new_size[1], new_size[0]) if swaps_dimensions else new_size)
        ImageOps.exif_transpose(img, in_place=True)
        resized = img
        if scale < 1:
            img.thumbnail(new_size, Image.Resampling.LANCZOS)
        elif img.size != new_size:
            resized = img.resize(new_size, Image.Resampling.LANCZOS)
        try:
            rgb = resized if resized.mode == "RGB" else resized.convert("RGB")
            try:
                prepared = PreparedPhoto(rgb.tobytes(), rgb.size, signature)
            finally:
                if rgb is not resized:
                    rgb.close()
        finally:
            if resized is not img:
                resized.close()
    if signature != file_signature(photo_path):
        raise PhotoChanged("Photo changed while it was loading")
    return prepared


def display_photo(screen, photo_path, prepared=None):
    try:
        if prepared is None:
            prepared = prepare_photo(photo_path, screen.get_size())
        if prepared.signature != file_signature(photo_path):
            return False
        # All Pygame calls stay on the display thread. frombuffer avoids another
        # RGB copy; the prepared bytes stay alive until blitting has finished.
        image = pygame.image.frombuffer(prepared.pixels, prepared.size, "RGB")
        screen_width, screen_height = screen.get_size()
        x = (screen_width - prepared.size[0]) // 2
        y = (screen_height - prepared.size[1]) // 2
        screen.fill("black")
        screen.blit(image, (x, y))
        pygame.display.flip()
        logger.debug("Displayed photo: %s", photo_path.name)
        return True
    except Exception as exc:
        logger.warning("Skipping unavailable image %s: %s", photo_path.name, exc)
        return False

def show_slideshow(settings=None, *,
                   control_url=None, url_display_seconds=30, new_photos=None,
                   status=None, index=None):
    if settings is None:
        settings = RuntimeSettings(DISPLAY_SECONDS, folders=get_cached_folders)
    pygame.init()
    logger.info("Slideshow started")
    loader = None
    running = True
    bad_photos = {}
    ahead = None
    try:
        screen = pygame.display.set_mode((0, 0), pygame.FULLSCREEN)
        logger.info("Display initialized: backend=%s, surface=%s, window=%s",
                    pygame.display.get_driver(), screen.get_size(), pygame.display.get_window_size())
        pygame.display.set_caption("Digital Frame")
        screen.fill("black")
        pygame.display.flip()
        current_url = control_url() if callable(control_url) else control_url
        overlay = SlideshowOverlay(screen, current_url, url_display_seconds)
        overlay.new_frame()
        observed_revision = 0
        loader = PhotoLoader(prepare_photo)

        def check():
            nonlocal running, observed_revision, current_url
            if callable(control_url):
                url = control_url()
                if url and url != current_url:
                    current_url = url
                    overlay.show_message(f"Control: {url}", url_display_seconds)
            if status is not None:
                overlay.set_network_problem(status.network_problem())
            message, revision = settings.notification_snapshot()
            if revision != observed_revision:
                overlay.show_message(message, 15)
                observed_revision = revision
            overlay.update()
            running = handle_events()
            return running

        def pause(milliseconds):
            overlay.wait(max(1, min(int(IDLE_SECONDS * 1000), milliseconds)))

        def eligible(path, folder):
            try:
                valid = (path.parent.parent == CACHE_DIR and path.is_file()
                         and not path.is_symlink() and not path.parent.is_symlink()
                         and (folder is None or path.parent.name == folder))
                failed = bad_photos.get(path)
                if failed and (failed[0] != file_signature(path) or time.monotonic() >= failed[1]):
                    bad_photos.pop(path, None)
                    failed = None
                return valid and not failed
            except OSError:
                return False

        def finished(future):
            while not future.done():
                if not check():
                    return False
                pause(50)
            return running

        while running and check():
            selected = settings.selected_folder
            photos = index.photos() if index is not None else get_cached_photos()
            bad_photos = {path: value for path, value in bad_photos.items() if path in photos}
            remaining = deque(path for path in photos if eligible(path, selected))
            seen = set()
            priority_paths = set()
            successes = 0
            failures = 0

            def queued():
                if new_photos is None:
                    return None
                while True:
                    try:
                        path = new_photos.get_nowait()
                    except Empty:
                        return None
                    if path.suffix.lower() in SUPPORTED_PHOTO_SUFFIXES and path not in seen and eligible(path, selected):
                        seen.add(path)
                        priority_paths.add(path)
                        return path

            def next_photo():
                path = queued()
                if path is not None:
                    return path
                while remaining:
                    path = remaining.popleft()
                    if path not in seen and eligible(path, selected):
                        seen.add(path)
                        return path
                return None

            path = next_photo()
            future = None
            if ahead is not None:
                if not finished(ahead[1]):
                    break
                if ahead[0] == path:
                    future = ahead[1]
                ahead = None
            if path is not None and future is None:
                future = loader.submit(path, screen.get_size())
            while path is not None and running:
                if not finished(future):
                    break
                # Selection and newly completed downloads are reconsidered only
                # at photo boundaries. Let an in-flight decode finish lazily.
                if settings.selected_folder != selected:
                    break
                urgent = queued() if path not in priority_paths else None
                if urgent is not None:
                    remaining.appendleft(path)
                    seen.discard(path)
                    path = urgent
                    future = loader.submit(path, screen.get_size())
                    continue
                prepared = None
                try:
                    prepared = future.result()
                    future = None  # Do not retain its RGB buffer during the interval.
                    if not eligible(path, selected) or prepared.signature != file_signature(path):
                        seen.discard(path)
                        remaining.appendleft(path)
                        success = False
                    else:
                        success = display_photo(screen, path, prepared)
                        if not success:
                            raise OSError("Image could not be rendered")
                except PhotoChanged:
                    seen.discard(path)
                    remaining.appendleft(path)
                    success = False
                except Exception as exc:
                    failures += 1
                    try:
                        bad_photos[path] = (file_signature(path), time.monotonic() + 60)
                    except OSError:
                        pass
                    logger.warning("Cannot display %s: %s", path.name, exc)
                    if status is not None:
                        status.report("Photos", f"Cannot display {path.name}: {exc}. Drive sync will check the cached file.")
                    success = False
                finally:
                    prepared = None
                    future = None
                deadline = pygame.time.get_ticks() + settings.display_seconds * 1000
                if success:
                    successes += 1
                    overlay.new_frame()
                path = next_photo()
                future = loader.submit(path, screen.get_size()) if path is not None else None
                if success:
                    if path is None:
                        upcoming = index.photos() if index is not None else get_cached_photos()
                        wrap = next((item for item in upcoming if eligible(item, selected)), None)
                        if wrap is not None:
                            ahead = (wrap, loader.submit(wrap, screen.get_size()))
                    # Only a single upcoming image is decoded during this wait.
                    while running and pygame.time.get_ticks() < deadline:
                        if not check():
                            break
                        pause(max(1, deadline - pygame.time.get_ticks()))
            if not running:
                break
            if path is not None and future is not None:
                ahead = (path, future)
            if settings.selected_folder != selected:
                continue
            if successes == 0:
                display_message(screen, "No readable photos available. Waiting for photos.")
                overlay.new_frame()
                if check():
                    pause(max(1000, int(IDLE_SECONDS * 1000)))
            elif failures == 0 and not bad_photos and status is not None:
                status.clear("Photos")
    finally:
        if loader is not None and not loader.close():
            logger.warning("Image loader is still completing its last decode")
        pygame.quit()
        logger.info("Slideshow stopped")


if __name__ == "__main__":
    from .runtime import main
    main()
