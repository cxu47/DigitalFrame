# Repository cleanup and display history plan

Date: 2026-09-10  
Reviewed baseline: `e9ee768`  
Status: planning only; implementation has not started.

## Scope and constraints

- Review and clean up stale configuration, code, dependencies, and documentation while preserving the current client functionality.
- Ignore all current testing: do not inspect, run, repair, delete, or reorganize `tests/`; do not use it to define intended behavior. Leave existing test tooling alone during this cleanup.
- Preserve `README.md`'s organization and the existing repository layout, except for the explicit changes listed below.
- Collect this and future change plans in the hidden `.plans/` directory, using descriptive filenames.
- Preserve the display investigation as historical reference for similar issues on other operating systems and Pi boards.
- Do not modify the local `.env`, credentials, tokens, cached photos, or demo asset.
- No dependency modernization, cloud-provider additions, new deployment services, or broad refactor.

## Functionality to preserve

The current code is the behavioral baseline:

- `python -m client.main` performs an initial sync, starts periodic background synchronization, and displays cached photos. The sync and slideshow modules also have standalone entry points.
- Google Drive uses read-only OAuth access, saved/refreshed tokens, and interactive authorization on port 8080 with automatic browser opening disabled.
- Synchronization skips filenames already present, downloads through `.part` files, and renames completed downloads into the cache. It does not refresh existing filenames or reconcile remote deletions.
- The slideshow uses sorted filenames, the existing supported extensions, an 800 × 600 display request, configurable timing, EXIF correction, and aspect-preserving scaling.
- Keep the memory-conscious image decoding/resizing and buffer release work, HEIC/HEIF support, waiting screen, invalid-image handling, Escape/close handling, and logging behavior.
- Keep SDL display selection configurable through the environment; device indices are machine-specific.

## Findings and planned work

### 1. Preserve and organize the display investigation

All eight tracked files currently in `logs/` belong to the historical investigation, including the two diagnostic scripts. They are not application log output destinations or part of the ignored automated test suite.

Proposed structure exception:

```text
logs/
  README.md
  banana-pi-m2-zero-display-issue/
    debug.log
    diagnose_display.py
    display-card0.log
    display-diagnostic.log
    magenta-scaled.log
    magenta.log
    magenta.sh
    slideshow-card0.log
```

- [ ] Move the eight files together, retaining original filenames and file contents so commands, output, and chronology remain traceable.
- [ ] Add `logs/README.md` with an inventory, symptom, recorded environment, diagnostic commands and working directory, observed differences, workaround, and limitations of the evidence.
- [ ] Record the environment reported by the captures: Banana Pi BPI-M2-Zero, Armbian, ARMv7, Python 3.14.4, Pygame 2.6.1, and SDL 2.32.10. Treat these as historical observations, not supported-version requirements.
- [ ] Explain that the default diagnostic run opened `/dev/dri/card1` with a 1920 × 1080 window, while the card-0 capture records `SDL_KMSDRM_DEVICE_INDEX=0` and an 800 × 600 window. The later slideshow capture records displayed photos. Software output alone does not prove what appeared on the physical screen.
- [ ] Explain how to identify the connected display and compare device mappings on another machine; do not prescribe card 0 universally. Preserve incomplete captures as incomplete evidence rather than inventing missing outcomes.
- [ ] Record commands for a fresh capture into a new location, avoiding overwriting historical files. Do not execute the diagnostic scripts during this planning task.

### 2. Reconcile dependencies and the obsolete Docker target

`Dockerfile` copies a nonexistent `server/` directory and starts `server.main:app` with Uvicorn. `requirements.txt` still includes server-era packages, and the Pygame requirement is commented out even though the client imports it.

Commit `2125050` explicitly associates the Pygame comment and the `pillow_heif` downgrade to 1.4.0 with Banana Pi/Armbian compatibility. These are not safe to undo blindly.

- [ ] Map client imports to direct requirements and inspect their dependency metadata before removing anything. Remove only confirmed server-only leftovers, such as FastAPI/Uvicorn and dependencies needed solely by the removed server. Keep dependencies required transitively by Google authentication or image handling.
- [ ] Leave test-related requirements unchanged, consistent with the testing exclusion.
- [ ] Preserve current runtime pins unless a concrete installation incompatibility requires a targeted adjustment; retain the hardware compatibility rationale in comments.
- [ ] Establish and document how Pygame is supplied on the working board and in a fresh installation. Make the installation path explicit without replacing a working system/custom SDL build with an incompatible wheel.
- [ ] Update the existing `Dockerfile` in place to copy and launch the client with `python -m client.main`. Resolve dependencies and runtime paths first. Do not recreate the old server or introduce Compose/deployment directories.
- [ ] Document the container's environment, cache, credential/token mounts, and display-access prerequisites. Separate a successful image build from actual physical display verification; retain any unverified hardware limitation explicitly.

### 3. Clean up active code and configuration in place

- [ ] `client/slideshow.py`: remove the obsolete `show_first_photo()` prototype after confirming it has no callers in active code or documented usage. Preserve `show_slideshow()` and its rendering pipeline; avoid unrelated formatting or display-mode changes.
- [ ] `client/storage/google_drive.py`: remove the superseded commented OAuth call while retaining the active port/browser behavior. Review comments and unused fields without redesigning authentication or synchronization.
- [ ] `client/config.py` and `.env.example`: align variable names and explanations, document `LOG_LEVEL` and path resolution relative to `client/`, and replace the real-looking Drive folder ID with a clear placeholder in the example only.
- [ ] Remove stale example annotations such as the creation date and ambiguous `SYNC_INTERVAL = 1 #60`. Preserve the effective interval unless deliberately changing it in a separately identified task.
- [ ] Label `SDL_KMSDRM_DEVICE_INDEX=0` as a setting from the recorded board workaround, rather than a universal default. Preserve the local `.env` and the application's environment-loading behavior.
- [ ] Review configuration failures: missing required values currently cause import-time path/float errors. If improved, provide clear validation messages while keeping valid configurations, environment precedence, timing values, and path behavior unchanged; do not silently introduce defaults.
- [ ] Review `client/main.py`, `client/sync.py`, and `client/logging_config.py` for stale references and unused code. Keep initial-sync ordering, background operation, cache identity, exception handling, and log output semantics stable.
- [ ] Review `.gitignore`, package files, and placeholders for obsolete references. Keep cache/secret exclusions and existing layout. Leave harmless `.gitkeep` files and `assets/demo.gif` intact.

### 4. Make only necessary README corrections

Keep the current title, section order, motivation, demo, roadmap, and historical Phase 1 description. The following content changes are justified by current inconsistencies or the installation cleanup:

- [ ] Correct the duplicate-filename limitation: current synchronization skips an existing destination, so a later same-name remote file is skipped rather than replacing it. Also state that changed remote content under an existing filename is not refreshed.
- [ ] Remove configurable image duration from “Potential Upgrades,” since `DISPLAY_SECONDS` already exists; mention it under “Current Features.” Keep future goals distinguishable from current capabilities.
- [ ] Replace the unconditional Google API “60 sec” timeout statement with a description supported by the installed transport configuration, or omit the numerical claim if it cannot be verified.
- [ ] Add a compact setup/run paragraph under “Project Status” covering dependencies/Pygame, copying `.env.example`, OAuth files, and `python -m client.main`; include necessary Docker limitations there without reorganizing the README.
- [ ] Link the historical display investigation and mention that a board-specific display setting may be needed. Do not mark all hardware deployment milestones complete based on diagnostic captures.

## Separate follow-up work, not part of this cleanup

The source review also exposes areas that could change behavior: Drive listing currently makes one request without pagination; existing cache filenames are never refreshed; remote deletions are not reconciled; an all-invalid slideshow can repeatedly loop without processing events through the successful-image path. Record these for separate fixes rather than silently expanding a functionality-preserving cleanup. Authentication redesign, configurable display size, sync scheduling changes, and additional providers are also out of scope.

## Implementation order and verification

1. Record the starting diff and preserve unrelated changes. Inventory the historical files before moving them.
2. Archive the investigation and write its index; verify that each original file survives with identical contents.
3. Resolve dependency provenance and installation assumptions, then update the Dockerfile and example configuration.
4. Apply the small active-code cleanup and necessary README corrections.
5. Check Python syntax and active-code references without invoking the existing tests. Review the final diff for accidental changes to timing, rendering, OAuth, cache semantics, or private local files.
6. For implementation validation, use focused manual smoke checks: installation/imports, cached-image display including EXIF and HEIC, empty/invalid-image handling, exit handling, and synchronization using temporary cache data. These are not a replacement automated suite. Keep any unavailable Drive or physical-board checks explicitly pending.
7. On an available target board, confirm actual visible output and continued slideshow operation with its known working SDL/Pygame setup. A headless run or log message cannot establish physical display success.

Completion means the historical evidence is preserved and discoverable, confirmed leftovers are corrected, valid existing configurations retain their behavior, README statements match the client, and verification results and hardware limitations are recorded. Tests remain untouched. Outside `logs/`, the only new file planned is this `.plans/repository-cleanup-and-display-history.md`; existing files are edited in place.
