# Repository cleanup and display history plan

Date: 2026-09-10  
Reviewed baseline: `e9ee768`  
Status: implemented on `feature/repository-cleanup-and-display-history`; local verification passed. Container, live Drive, and physical-board verification remain pending as recorded below.
Implementation baseline: `ff0061c` (merged `main`).

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

- [x] Move the eight files together, retaining original filenames and file contents so commands, output, and chronology remain traceable.
- [x] Add `logs/README.md` with an inventory, symptom, recorded environment, diagnostic commands and working directory, observed differences, workaround, and limitations of the evidence.
- [x] Record the environment reported by the captures: Banana Pi BPI-M2-Zero, Armbian, ARMv7, Python 3.14.4, Pygame 2.6.1, and SDL 2.32.10. Treat these as historical observations, not supported-version requirements.
- [x] Explain that the default diagnostic run opened `/dev/dri/card1` with a 1920 × 1080 window, while the card-0 capture records `SDL_KMSDRM_DEVICE_INDEX=0` and an 800 × 600 window. The later slideshow capture records displayed photos. Software output alone does not prove what appeared on the physical screen.
- [x] Explain how to identify the connected display and compare device mappings on another machine; do not prescribe card 0 universally. Preserve incomplete captures as incomplete evidence rather than inventing missing outcomes.
- [x] Record commands for a fresh capture into a new location, avoiding overwriting historical files. Do not execute the diagnostic scripts during this planning task.

### 2. Reconcile dependencies and the obsolete Docker target

`Dockerfile` copies a nonexistent `server/` directory and starts `server.main:app` with Uvicorn. `requirements.txt` still includes server-era packages, and the Pygame requirement is commented out even though the client imports it.

Commit `2125050` explicitly associates the Pygame comment and the `pillow_heif` downgrade to 1.4.0 with Banana Pi/Armbian compatibility. These are not safe to undo blindly.

- [x] Map client imports to direct requirements and inspect their dependency metadata before removing anything. Remove only confirmed server-only leftovers, such as FastAPI/Uvicorn and dependencies needed solely by the removed server. Keep dependencies required transitively by Google authentication or image handling.
- [x] Leave test-related requirements unchanged, consistent with the testing exclusion.
- [x] Preserve current runtime pins unless a concrete installation incompatibility requires a targeted adjustment; retain the hardware compatibility rationale in comments.
- [x] Establish and document how Pygame is supplied on the working board and in a fresh installation. Make the installation path explicit without replacing a working system/custom SDL build with an incompatible wheel.
- [x] Update the existing `Dockerfile` in place to copy and launch the client with `python -m client.main`. Resolve dependencies and runtime paths first. Do not recreate the old server or introduce Compose/deployment directories.
- [x] Document the container's environment, cache, credential/token mounts, and display-access prerequisites. Separate a successful image build from actual physical display verification; retain any unverified hardware limitation explicitly.

### 3. Clean up active code and configuration in place

- [x] `client/slideshow.py`: remove the obsolete `show_first_photo()` prototype after confirming it has no callers in active code or documented usage. Preserve `show_slideshow()` and its rendering pipeline; avoid unrelated formatting or display-mode changes.
- [x] `client/storage/google_drive.py`: remove the superseded commented OAuth call while retaining the active port/browser behavior. Review comments and unused fields without redesigning authentication or synchronization.
- [x] `client/config.py` and `.env.example`: align variable names and explanations, document `LOG_LEVEL` and path resolution relative to `client/`, and retain the user's Drive folder ID in the example. Per the user's follow-up, set the default log level to `INFO`.
- [x] Remove stale example annotations such as the creation date and ambiguous `SYNC_INTERVAL = 1 #60`. Preserve the effective interval unless deliberately changing it in a separately identified task.
- [x] Label `SDL_KMSDRM_DEVICE_INDEX=0` as a setting from the recorded board workaround, rather than a universal default. Preserve the local `.env` and the application's environment-loading behavior.
- [x] Review configuration failures: missing required values currently cause import-time path/float errors. If improved, provide clear validation messages while keeping valid configurations, environment precedence, timing values, and path behavior unchanged; do not silently introduce defaults.
- [x] Review `client/main.py`, `client/sync.py`, and `client/logging_config.py` for stale references and unused code. Keep initial-sync ordering, background operation, cache identity, exception handling, and log output semantics stable.
- [x] Review `.gitignore`, package files, and placeholders for obsolete references. Keep cache/secret exclusions and existing layout. Leave harmless `.gitkeep` files and `assets/demo.gif` intact.

### 4. Make only necessary README corrections

Keep the current title, section order, motivation, demo, roadmap, and historical Phase 1 description. The following content changes are justified by current inconsistencies or the installation cleanup:

- [x] Correct the duplicate-filename limitation: current synchronization skips an existing destination, so a later same-name remote file is skipped rather than replacing it. Also state that changed remote content under an existing filename is not refreshed.
- [x] Remove configurable image duration from “Potential Upgrades,” since `DISPLAY_SECONDS` already exists; mention it under “Current Features.” Keep future goals distinguishable from current capabilities.
- [x] Replace the unconditional Google API “60 sec” timeout statement with a description supported by the installed transport configuration, or omit the numerical claim if it cannot be verified.
- [x] Add a compact setup/run paragraph under “Project Status” covering dependencies/Pygame, copying `.env.example`, OAuth files, and `python -m client.main`; include necessary Docker limitations there without reorganizing the README.
- [x] Link the historical display investigation and mention that a board-specific display setting may be needed. Do not mark all hardware deployment milestones complete based on diagnostic captures.

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


## Implementation record — 2026-09-10

- Created `feature/repository-cleanup-and-display-history` from clean local `main` at `ff0061c`.
- Moved all eight investigation files into the proposed case folder without changing their contents. Added `logs/README.md` with an inventory, captured environment, evidence limitations, device-selection guidance, and commands that preserve the original captures.
- Removed the unused `show_first_photo()` prototype and commented OAuth alternative. The remaining slideshow syntax tree and Google Drive logic are unchanged. Reviewed `client/main.py`, `client/sync.py`, `client/logging_config.py`, `.gitignore`, package files, placeholders, and the demo reference; no cleanup was needed there.
- Added named errors for missing previously required configuration values and malformed timing numbers. Valid values, relative/absolute path handling, dotenv precedence, and defaults are preserved. The Drive folder ID remains optional at import time to preserve cache-only slideshow usage.
- Updated `.env.example` with timing/path explanations, `LOG_LEVEL`, and an optional board-specific SDL setting. Restored the user's Drive folder ID in the example after their clarification that it should remain there. Changed the configuration fallback and example log level from `DEBUG` to `INFO` as explicitly requested; existing environment overrides still take precedence. No local `.env`, credentials, tokens, or cached photos were changed.
- Removed FastAPI, Uvicorn, Starlette, Pydantic/core, annotated-doc/types, typing-inspection, and python-multipart after reviewing imports and installed dependency metadata. All retained pins are unchanged. Existing pytest-related pins and HTTP tooling (`httpx`, `httpcore`, `h11`, `anyio`, and their shared dependencies) remain because test/tooling cleanup is excluded. `click` remains available for the existing OAuth/dotenv CLI tooling.
- Kept Pygame outside `requirements.txt` so dependency installation preserves an existing board build. Documented an explicit wheel installation for fresh supported platforms; Docker installs that wheel with the client dependencies. The archived board reports Pygame in its virtual environment and system SDL libraries, but its exact original build/install command is unknown.
- Retargeted the existing Dockerfile to the client, added SDL runtime libraries, and limited source copies to Python files so cached photos and secrets are excluded from the image. Documented configuration/data mounts, reuse of a natively authorized token, and host display requirements. Initial OAuth still binds to localhost; no authentication redesign was introduced.
- Corrected README feature/cache/timeout statements and added setup and archive references within the existing sections. The README's heading sequence and the layout outside the explicitly planned `logs/` archive are preserved.

### Verification results

- Fresh installation succeeded in a temporary Python 3.12.3 environment on Linux AArch64 using the edited requirements and `pygame==2.6.1`; `pip check` reported no broken requirements. This used `pillow_heif==1.4.0`, not the existing workspace environment's 1.5.0.
- All active Python sources parsed successfully. SHA-256 comparisons confirmed all eight archived files are byte-identical to their originals.
- Focused temporary smoke checks passed for module imports, example configuration, old/new configuration equivalence (including absolute and empty relative paths), missing Drive folder ID for cache-only usage, dotenv precedence, missing required values, and malformed timing numbers.
- Pygame's dummy display passed JPEG/EXIF orientation, PNG scaling/letterboxing, HEIC rendering, supported-file sorting/filtering, invalid/missing image handling, Escape/close handling, and both populated-cache and empty-cache slideshow exit checks.
- Synchronization checks used a temporary cache and simulated remote listings/downloads. Existing filenames and duplicate names were skipped, completed downloads replaced `.part` files, failed partial downloads were cleaned up, listing failures were handled, and local-only files remained intact.
- Temporary validation code and generated images stayed outside the repository. No existing tests were inspected, run, changed, or added. No historical diagnostic script was executed and no live OAuth/Drive request was made.
- Final diff and documentation-link checks passed. The only additional documentation file is `logs/README.md`; this existing plan was updated with the results.

### Pending environment-dependent verification

- [ ] Build and run the image when Docker is available. `docker version` reports that Docker Desktop's WSL integration is unavailable in this distro; package installation success does not establish a successful container build.
- [ ] Verify live OAuth/token refresh and Drive synchronization on the configured deployment using temporary cache data. Local smoke checks used simulated remote data and did not access private credentials.
- [ ] Confirm visible output and continued slideshow operation on the physical board/display with its known working Pygame/SDL setup. The AArch64 dummy-display run is not ARMv7 hardware validation. Record visibility and restart observations with any new case captures.
