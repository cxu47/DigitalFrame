python -u - <<'PY'
import os
import pygame

print("Pygame:", pygame.version.ver)
print("SDL:", pygame.get_sdl_version())
for key in ("SDL_VIDEODRIVER", "DISPLAY", "WAYLAND_DISPLAY",
            "XDG_SESSION_TYPE"):
    print(f"{key}={os.environ.get(key)!r}")

pygame.display.init()
try:
    screen = pygame.display.set_mode((800, 600))
    print("Actual display driver:", pygame.display.get_driver())
    print("Screen size:", screen.get_size())

    start = pygame.time.get_ticks()
    while pygame.time.get_ticks() - start < 10000:
        pygame.event.pump()
        screen.fill((255, 0, 255))
        pygame.display.flip()
        pygame.time.wait(50)
finally:
    pygame.quit()
PY
