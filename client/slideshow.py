from pathlib import Path
import pygame

CACHE_DIR = Path("client/cache")


def get_cached_photos():
    return [
        path
        for path in CACHE_DIR.iterdir()
        if path.is_file() and path.name != ".gitkeep"
    ]


def show_first_photo():
    photos = get_cached_photos()

    if not photos:
        print("No cached photos available.")
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
        for event in pygame.event.get():
            if event.type == pygame.QUIT:
                running = False

            elif event.type == pygame.KEYDOWN:
                if event.key == pygame.K_ESCAPE:
                    running = False

    pygame.quit()


if __name__ == "__main__":
    show_first_photo()
