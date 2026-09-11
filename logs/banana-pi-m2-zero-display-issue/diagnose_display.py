"""Run on the Pi: python -u diagnose_display.py --scaled > display-diagnostic.log 2>&1."""

import argparse
import os
from pathlib import Path
import platform
import sys
import time


def read(path):
    try:
        return Path(path).read_text().strip().replace("\x00", " ")
    except OSError as exc:
        return f"unavailable ({exc.strerror})"


def devices():
    print("Active virtual terminal:", read("/sys/class/tty/tty0/active"))
    print("Framebuffer list:", read("/proc/fb"))
    for card in sorted(Path("/sys/class/drm").glob("card*")):
        if (card / "status").exists():
            print(f"Connector {card.name}: status={read(card / 'status')}, "
                  f"enabled={read(card / 'enabled')}, "
                  f"modes={read(card / 'modes').splitlines()}")
        elif card.name[4:].isdigit():
            driver = card / "device/driver"
            print(f"DRM {card.name}: device={card.resolve()}, "
                  f"driver={driver.resolve() if driver.exists() else 'unavailable'}")
    for fb in sorted(Path("/sys/class/graphics").glob("fb[0-9]*")):
        print(f"Framebuffer {fb.name}: name={read(fb / 'name')}, "
              f"device={(fb / 'device').resolve()}")


def open_graphics_devices():
    for fd in sorted(Path("/proc/self/fd").glob("*")):
        try:
            target = os.readlink(fd)
        except OSError:
            continue
        if target.startswith(("/dev/dri/", "/dev/fb")):
            print(f"Open graphics device: fd={fd.name}, path={target}")
    libraries = set()
    for line in read("/proc/self/maps").splitlines():
        parts = line.split(maxsplit=5)
        if len(parts) == 6 and any(name in parts[5] for name in
                                  ("libSDL2", "libEGL", "libGLES", "libgbm", "_dri.so")):
            libraries.add(parts[5])
    for library in sorted(libraries):
        print("Loaded graphics library:", library)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--scaled", action="store_true")
    args = parser.parse_args()
    print("Python:", sys.executable, sys.version)
    print("Kernel:", platform.system(), platform.release(), platform.machine())
    print("Board:", read("/proc/device-tree/model"))
    print("OS:", read("/etc/os-release"))
    try:
        print("Input terminal:", os.ttyname(0))
    except OSError:
        print("Input terminal: stdin is not a terminal")
    for key in ("SDL_VIDEODRIVER", "SDL_RENDER_DRIVER", "SDL_KMSDRM_DEVICE_INDEX",
                "SDL_KMSDRM_REQUIRE_DRM_MASTER", "PYGAME_FORCE_SCALE",
                "PYGAME_DISPLAY", "DISPLAY", "WAYLAND_DISPLAY", "XDG_SESSION_TYPE"):
        print(f"{key}={os.environ.get(key)!r}")
    devices()

    import pygame

    print("Pygame:", pygame.version.ver, "from", pygame.__file__)
    print("SDL:", pygame.get_sdl_version())
    try:
        pygame.display.init()
        print("Display driver:", pygame.display.get_driver())
        print("Desktop sizes:", pygame.display.get_desktop_sizes())
        flags = pygame.SCALED if args.scaled else 0
        screen = pygame.display.set_mode((800, 600), flags)
        print("Surface:", screen.get_size(), "Window:", pygame.display.get_window_size())
        print("Window-system info:", pygame.display.get_wm_info())
        open_graphics_devices()
        start = time.monotonic()
        frames = 0
        running = True
        while running and time.monotonic() - start < 10:
            for event in pygame.event.get():
                if event.type == pygame.QUIT or (
                    event.type == pygame.KEYDOWN and event.key == pygame.K_ESCAPE
                ):
                    running = False
            screen.fill((255, 0, 255))
            pygame.display.flip()
            frames += 1
            if frames == 1:
                print("First flip returned; surface pixel:", screen.get_at((0, 0)))
                print("Window active:", pygame.display.get_active())
                devices()
            pygame.time.wait(50)
        print("Test loop finished; completed flips:", frames)
    finally:
        pygame.quit()
        print("Pygame shut down")


if __name__ == "__main__":
    main()
