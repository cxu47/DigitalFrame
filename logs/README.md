# Historical display investigations

This directory preserves troubleshooting evidence, including diagnostic scripts. The client logs to its configured Python logging stream; it does not write new runs into this archive. Keep future cases in separate folders named for the board and symptom, and record the OS, graphics stack, commands, observations, and outcome for each case.

## Banana Pi M2 Zero: photos not visible

The [original investigation files](banana-pi-m2-zero-display-issue/) were collected while resolving a case where the application reported displaying photos but the expected image was not visible on the connected display. All eight original files retain their names and contents. The application captures contain timestamps from 2026-09-10; some diagnostic captures have no timestamps.

The recorded environment was a Banana Pi BPI-M2-Zero running Armbian community 26.11.0-trunk.19 (Ubuntu 26.04), Linux 6.18.45-current-sunxi on ARMv7, Python 3.14.4, Pygame 2.6.1, and SDL 2.32.10. The session was a local TTY using KMSDRM, with no X11 or Wayland display variables. These describe this case, not a support matrix for other machines.

| File | Evidence or purpose |
| --- | --- |
| [debug.log](banana-pi-m2-zero-display-issue/debug.log) | Initial client run with Drive sync and slideshow logging. |
| [magenta.sh](banana-pi-m2-zero-display-issue/magenta.sh) | Ten-second magenta-screen probe requesting 800 × 600; prints the selected backend and actual surface size. |
| [magenta.log](banana-pi-m2-zero-display-issue/magenta.log) | KMSDRM probe reporting a 1920 × 1080 surface. |
| [magenta-scaled.log](banana-pi-m2-zero-display-issue/magenta-scaled.log) | Follow-up probe reporting an 800 × 600 surface. The exact modified command/script used for this capture was not preserved. |
| [diagnose_display.py](banana-pi-m2-zero-display-issue/diagnose_display.py) | Device, connector, SDL/library, environment, and magenta-screen diagnostics, with an optional `--scaled` flag. |
| [display-diagnostic.log](banana-pi-m2-zero-display-issue/display-diagnostic.log) | Default-device capture: 800 × 600 surface, 1920 × 1080 window, `/dev/dri/card1` opened, and 170 completed flips. |
| [display-card0.log](banana-pi-m2-zero-display-issue/display-card0.log) | Capture with `SDL_KMSDRM_DEVICE_INDEX=0`: 1280 × 720 desktop and an 800 × 600 surface/window. It ends at the surface/window report; no completed loop or device-open report is recorded. |
| [slideshow-card0.log](banana-pi-m2-zero-display-issue/slideshow-card0.log) | Later slideshow capture reporting PNG and HEIC photos displayed, followed by shutdown. The filename associates it with the card-0 run; it does not print the selected device itself. |

## Finding and workaround

The default diagnostic capture shows SDL opening `card1`, the `simple-framebuffer` device with an `Unknown-1` connector. The board's `card0` was the `sun4i-drm` display device with a connected HDMI connector; `card2` was the Lima GPU. Successful flips and a magenta surface pixel did not establish that output reached the intended physical screen.

The recorded workaround selected `SDL_KMSDRM_DEVICE_INDEX=0`. The card-0 capture shows a different desktop size and an 800 × 600 window, and the subsequent slideshow log reports displayed photos. This supports investigating device selection when the same symptom recurs. The captures do not independently verify physical visibility or establish a universal cause for blank displays. The NEON warning is also preserved; the evidence does not establish it as the cause.

Before applying the workaround elsewhere, compare the diagnostic output's DRM cards, driver names, connector status, modes, and open graphics devices with the actual connected monitor. Card numbering can differ by board, OS, or boot. Select the index for that machine rather than assuming zero. Use the physical display to confirm the outcome.

## Capture a new case

Run from the repository root in the board's intended display session, using its working Python/Pygame environment. The diagnostic scripts do not load the application's `.env`, so pass SDL settings explicitly. Each command below writes to a fresh temporary directory, preserving the archive:

```bash
source .venv/bin/activate
capture_dir=$(mktemp -d /tmp/digitalframe-display.XXXXXX)
python -u logs/banana-pi-m2-zero-display-issue/diagnose_display.py \
  > "$capture_dir/display-default.log" 2>&1
python -u logs/banana-pi-m2-zero-display-issue/diagnose_display.py --scaled \
  > "$capture_dir/display-scaled.log" 2>&1
bash logs/banana-pi-m2-zero-display-issue/magenta.sh \
  > "$capture_dir/magenta.log" 2>&1
```

These runs inherit the shell environment, which the diagnostic output records. After inspecting the device mappings, select the appropriate index. This example uses the original board's index and must be adjusted for another machine:

```bash
SDL_KMSDRM_DEVICE_INDEX=0 python -u \
  logs/banana-pi-m2-zero-display-issue/diagnose_display.py \
  > "$capture_dir/display-selected-device.log" 2>&1
```

For a configured client, `SDL_KMSDRM_DEVICE_INDEX=0 python -u -m client.slideshow > "$capture_dir/slideshow-selected-device.log" 2>&1` records a cache-only slideshow run. Ensure the configured cache directory exists first; exit with Escape or close the window. Record whether magenta and photos actually appeared, the commands and index used, and whether the result survived a restart. Store useful new evidence in its own case folder with an accompanying explanation.

Pygame was loaded from the board's `.venv`, with SDL libraries under `/usr/lib/arm-linux-gnueabihf/` (including `sdl2-classic`). The original installation/build command is absent from this archive. Preserve that working environment when reproducing this case; a desktop wheel may use a different SDL build.
