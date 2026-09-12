# DigitalFrame

DigitalFrame is a prototype for a self-updating digital photo frame. The Linux client securely connects to a third-party cloud storage provider, synchronizes images to a local cache, and displays them as a continuous slideshow.

## Motivation

This project began as a way to privately share family photos with relatives in China. Existing digital frames and cloud services did not fully meet our needs because of regional internet compatibility and privacy concerns. DigitalFrame explores a homemade alternative that can securely retrieve photos from cloud storage without requiring the recipient to manage uploads, accounts, or downloads.

A future version will run on a Raspberry Pi-style single-board computer connected to a portable display, turning the prototype into a standalone digital frame.

Although the application is intentionally simple, it also provides an opportunity to practice production-oriented software engineering skills, including client-server architecture, API development, cloud authentication, automated testing, containerization, and CI/CD. Development tasks are organized as GitHub issues, implemented on dedicated feature branches, and submitted through pull requests—even when I am both the author and reviewer—to practice a structured development and review workflow.

## Demo

![DigitalFrame demo](assets/demo.gif)

<img src="assets/hardware_v1.png" alt="DigitalFrame demo" width="80%">

## Project Goals

The DigitalFrame client is designed to:

- Connect to a configured cloud storage provider
- Retrieve available image files
- Download new or updated images to a local cache
- Remove local images that are no longer available remotely
- Periodically check for cloud updates in the background
- Display cached images as a continuous slideshow
- Run on a Raspberry Pi, Banana Pi, or similar Linux device

## Current Features

- Google Drive authentication using OAuth credentials
- Remote photo listing and downloading
- Background synchronization at a configurable interval
- Newly downloaded photos play next after the current photo finishes, without renaming files
- One-level photo albums mirrored in the local cache, with an All/folder selector
- Manifest-based detection of additions, edits, moves, renames, and deletions
- Temporary download files to prevent incomplete images from being displayed
- Continuous slideshow using Pygame and Pillow
- Configurable image display duration through `DISPLAY_SECONDS` and a plain HTML control panel on the local Wi-Fi
- Automatic EXIF orientation correction
- Fullscreen display at the current screen resolution, with proportional photo scaling and centered black bars
- Graceful handling of missing or invalid cached images
- Waiting screen when no cached photos are available

## Important Limitations

- Only photos directly inside immediate child folders are included. Loose root photos, deeper nested folders, and Drive shortcuts are ignored.
- Keep one syncing process per cache directory. The manifest tracks files created by sync; unrelated local files and legacy root photos are left in place.
- The project is currently a prototype and has not undergone a complete security review.
- Google Drive requests use the Google API client's transport timeout behavior; the application does not configure its own request timeout.

## Potential Upgrades

- Randomized slideshow order
- Collage layouts
- Encrypted local storage
- Improved authentication and security protocols
- Configurable overwrite and duplicate-handling policies
- Cache validation during startup
- User-configurable cloud provider or server URL
- Improved network failure recovery

## Development Progress

### Phase 1 - Local FastAPI Prototype ([release/1.x](https://github.com/cxu47/DigitalFrame/tree/release/1.x))

- [x] Create the server and client project structure
- [x] Add Docker configuration
- [x] Create a photo-upload endpoint
- [x] Create a photo-listing endpoint
- [x] Download files using a temporary extension until completion
- [x] Continuously check the local cache for displayable photos
- [x] Periodically synchronize the cache in a background thread
- [x] Display cached photos as a slideshow

### Phase 2 - Google Drive Integration

- [x] Configure Google Drive OAuth credentials and tokens
- [x] Retrieve and process the remote file listing
- [x] Download photos from Google Drive
- [x] Filter out folders and unsupported file types
- [x] Add HEIC and other iPhone image-format support
- [x] Reconcile remote deletions with the local cache

### Phase 3 - Alibaba Cloud OSS Integration

- [ ] Evaluate Alibaba Cloud OSS compatibility
- [ ] Configure secure long-term authentication
- [ ] Confirm token and credential expiration behavior
- [ ] Implement OSS photo listing and downloading
- [ ] Test connectivity from both the United States and China

### Phase 4 - Hardware Deployment

- [x] Deploy the client on a Raspberry Pi-style device
- [x] Connect and configure a portable display
- [ ] Configure automatic startup after reboot
- [ ] Test unattended synchronization and recovery
- [ ] Assemble the components into a standalone frame enclosure

## Project Status

DigitalFrame is under active development. The current implementation demonstrates the core workflow of authenticating with cloud storage, synchronizing photos into a local cache, and displaying them as a continuously updating slideshow.

### Installation and configuration

DigitalFrame runs natively as the intended Linux user. Install [uv](https://docs.astral.sh/uv/getting-started/installation/) and a compatible Python interpreter (declared range: 3.12–3.14). The uv workflow was validated with uv 0.12.13 and Python 3.12.3 on Linux AArch64; the archived ARMv7/Python 3.14 board still needs migration verification. uv manages Python packages; the OS still supplies display drivers, session/device access, and any native SDL/image libraries needed by your chosen build.

Run these commands from the repository root for a **fresh standard display installation**:

```bash
uv sync --locked --no-dev
cp -n .env.example .env
```

This installs the base application, Pygame 2.6.1, FastAPI, Uvicorn, and form handling together in one uv environment. A compatible wheel or build environment must exist for the selected Python/platform. `pillow_heif` remains pinned to 1.4.0 for the earlier Banana Pi/Armbian compatibility adjustment. The `dev` group is excluded from runtime installation.

For an **existing board with a working custom Pygame/SDL build**, validate this unified installation in a separate checkout/environment before migrating the working frame. The [historical display investigation](logs/README.md) records the board's interpreter, Pygame/SDL versions, and device-selection workaround, but its original Pygame build command is unknown. The normal locked package has not yet been verified on that ARMv7/Python 3.14 board.

If the board needs a custom wheel, build or obtain one for its interpreter ABI and platform, record the build procedure and artifact hash, and declare a platform-specific Pygame source in `pyproject.toml` before regenerating `uv.lock`. This source must resolve reproducibly on a fresh board. The old `--inexact` approach does not establish that the now-declared Pygame dependency uses the required custom graphics stack. Keep the existing installation until visible output is verified. OS graphics libraries remain system prerequisites, and a copied laptop `.venv` is not a deployment method. [uv package sources](https://docs.astral.sh/uv/concepts/projects/dependencies/)

In `.env`, confirm `GOOGLE_DRIVE_FOLDER_ID` and place the Google OAuth client JSON at `client/secrets/google_credentials.json` for the example configuration. Create cache/secrets directories if using custom paths. Relative paths resolve from `client/`, credential/token filenames resolve within the secrets directory, and existing environment variables override `.env`. Timing values are seconds; `DISPLAY_SECONDS` must be a positive integer (for example `5`, not `5.0`). `IDLE_SECONDS` and `SYNC_INTERVAL` still accept decimals. `LOG_LEVEL` defaults to `INFO`.

### Running the frame

The Typer CLI provides these commands after installation:

```bash
uv run --no-sync digitalframe run        # Sync + slideshow + Wi-Fi control panel
uv run --no-sync digitalframe slideshow  # Cached slideshow + panel; no cloud access
uv run --no-sync digitalframe sync       # One sync; no display required
uv run --no-sync digitalframe --help
```

The unified installation supplies Pygame and the control server for `run` and `slideshow`. Help needs no `.env` or display dependencies; no arguments show help. For a cache-only slideshow, place photos inside album directories within the configured cache directory; a missing or empty cache shows the waiting screen. Exit the slideshow with Escape or by closing its window.

At each startup, the slideshow automatically uses the selected display's current resolution in fullscreen, following [Pygame's display sizing behavior](https://www.pygame.org/docs/ref/display.html#pygame.display.set_mode). It reads the resolution through the OS/SDL display backend; no screen dimensions or aspect ratio need to be configured in the app. Photos keep their original aspect ratio after EXIF orientation correction and fit entirely on screen, with black bars on the sides or top and bottom as needed. For example, a 4:3 photo on a 1280×720 display occupies 960×720 pixels with 160-pixel bars on each side; this is an example, not a fixed output size. The startup log reports the display backend, rendering surface size, and window size. Restart the app after switching HDMI displays or changing the OS display mode. If photos still appear stretched, check that the OS display resolution matches the panel's aspect ratio and that the monitor's own scaling setting preserves proportions.

Initial Drive authorization prints a URL without opening a browser and waits for a localhost callback on port 8080. The authorizing browser must reach that callback; use SSH port forwarding when authorizing a remote board. Tokens are created/refreshed in the configured secrets directory. The `slideshow` command does not initiate authorization.

`--no-sync` keeps normal startup separate from package changes. After installation, `.venv/bin/digitalframe` runs the same commands directly. `python -m client` exposes the same CLI in the selected environment; the existing `python -m client.main`, `python -m client.slideshow`, and `python -m client.sync` entry points still work. Installation is editable from this checkout; keep the checkout available and run from its root. Standalone wheel deployment with relocated configuration/data is not supported by this workflow.

During `digitalframe run`, each successfully downloaded photo enters a shared in-memory queue as soon as its complete file is published to the cache. The current photo finishes its configured interval, then queued photos play in download-completion order before the regular alphabetical rotation resumes where it left off. Photos promoted from that rotation are skipped at their original position for the current cycle. Ordinary filenames and photo metadata stay unchanged; duplicate or unsafe filenames are adjusted as described below. Failed downloads are not queued; unreadable images are skipped. Already cached files are not promoted again on every sync.

New arrivals are detected on the next sync, controlled by `SYNC_INTERVAL`; this is polling, not a live Google Drive notification. Initial downloads are also queued, though the existing startup sync finishes before the slideshow opens. The queue lasts for the current `run` process. A separate `digitalframe sync` process does not send priority notifications to a cache-only `slideshow` process; those files join its ordinary rotation on the next cache scan.

### Photo folders and synchronization

Keep `GOOGLE_DRIVE_FOLDER_ID` pointed at the same parent folder. Organize its photos one level below it, for example:

```text
Configured Drive folder          Local cache
├── fun things/                  ├── fun things/
│   └── party.jpg                │   └── party.jpg
├── kids/                        ├── kids/
│   └── portrait.heic            │   └── portrait.heic
├── summer/                      ├── summer/
│   └── beach.jpg                │   └── beach.jpg
└── loose.jpg  (ignored)         └── .photos.json  (sync manifest)
```

Every startup selects **All**, playing photos from every album. Loose photos in either root and photos more than one folder deep are ignored. Existing flat-cache photos stay on disk but no longer play; move the photos into Drive albums and run sync to populate the new cache layout. Empty Drive albums also get local directories and appear in the selector.

Every sync fetches all listing pages for the parent and its immediate albums. A saved `.photos.json` manifest records Drive file IDs, relative cache paths, and content checksums (falling back to modification time and size). A SHA-256 hash of this metadata skips reconciliation when the tree is unchanged and its cached files exist. The remote metadata still needs to be listed on each interval; the hash avoids repeated downloads and cache changes. See Google's [file metadata](https://developers.google.com/workspace/drive/api/reference/rest/v3/files) and [paginated listings](https://developers.google.com/workspace/drive/api/reference/rest/v3/files/list).

New or edited photos download through temporary files and become visible only when complete. Renames and moves reuse unchanged cached content. Deleted photos and removed albums are cleaned up after a complete successful listing; listing failures preserve the cache, and failed downloads retry on the next sync. An older copy of an edited photo is retained until the update succeeds where its path is still available. Only manifest-tracked photos and empty old album directories are removed. Duplicate names within a folder get distinct suffixes; path separators and unsafe names are normalized to keep files within the cache. Same filenames in different albums remain independent.

New-photo priority respects the selected album. Photos from other albums join the normal rotation when you select that album or All. If the selected album disappears or is renamed during sync, selection falls back to All. An existing but empty selected album shows the waiting screen.

### Control the frame from another device

Assume the frame and your phone, tablet, or computer are already connected to the same Wi-Fi, with device-to-device traffic allowed. When `run` or `slideshow` starts, the frame detects its network address and logs the browser URL, for example **`http://192.168.1.42:8000`**. Open the displayed URL on the other device. `CONTROL_HOST` defaults to `0.0.0.0` (listen on network interfaces), and `CONTROL_PORT` defaults to `8000`; the browser uses the actual frame IP, not `0.0.0.0` or the other device's `localhost`.

The URL also appears at the **top-left of the slideshow for 30 seconds**, including on the waiting screen when no photos are cached. Set `CONTROL_URL_DISPLAY_SECONDS` in `.env` to change this duration; it accepts nonnegative whole seconds, with `0` disabling the overlay. The countdown begins when the slideshow opens, after any initial sync. The overlay disappears during a long photo interval without advancing or reloading the photo. This startup setting is separate from the photo duration controlled by the form.

Address detection uses the operating system's route-selected local address, with a fallback to active Linux interfaces when no route is available. It does not hard-code a board model or interface name, send a probe datagram, or require internet access. An explicit `CONTROL_HOST` uses that listener's address. If detection fails, the server continues with a warning and no URL overlay; check the board's network settings or router device list. Detection runs at startup, so restart the application after an address change. On machines with several networks or a VPN, the selected route may belong to another network; bind `CONTROL_HOST` to the desired local address if needed.

Enter positive whole seconds and click **Apply**. The page uses a normal HTML form, without JavaScript, CSS, or internet assets. The server accepts integer text such as `5`, validates it, and redirects back to the page with the updated duration. Letters, blanks, decimal notation such as `5.0`, fractions, zero, and negative values show an error directly below the form. Invalid submissions preserve the active setting and keep the slideshow running; correct the input and submit again.

Use the **Photo folder** dropdown and **Apply folder** to choose an album or **All**. This is a second plain HTML form. Refresh the page after a sync to see added, renamed, or removed albums.

Each accepted duration Apply action shows **“Seconds per photo: …” for 15 seconds** in the same top-left banner. **Apply folder** shows **“Photo folder: …”** for the same duration, including when All is selected or the same folder is submitted again. If sync removes the selected folder, the automatic fallback also shows **“Photo folder: All”**. It replaces any visible startup URL; the latest accepted duration or folder submission replaces the message and restarts the 15-second timer. Invalid submissions do not trigger a message. Setting confirmations still appear when the startup URL overlay is disabled.

Changes apply starting with the next successfully displayed photo. The current photo finishes its original interval. Settings live in memory: restarting restores `DISPLAY_SECONDS` from configuration and selects All folders. Refreshing the page displays the current setting. The panel starts before initial cloud sync and also works in cache-only mode without internet access. The `sync` command does not start it.

The panel is intended for a trusted local network and has no login. No Wi-Fi setup or public hosting is included. Escape, window close, or Ctrl+C stops the panel with the display. An unavailable port produces a startup error; unexpected server exit stops the display with an error. Run one application process; a separate Uvicorn process or multiple workers would not share these runtime settings. Google authorization continues to use its separate port 8080.

### Maintenance and deployment

`pyproject.toml` declares runtime dependencies and the development group; the generated `uv.lock` fixes their resolved versions. `requirements.txt` is no longer maintained. Install runtime packages and development tooling together with `uv sync --locked`. Resolve any board-specific Pygame source as described above before migrating that board.

### Automated tests

After installing development tooling and Pygame, run from the repository root:

```bash
uv run --no-sync python -m pytest -q
```

The suite checks the main workflows: saved/refreshed/new Drive authorization, photo listing and chunked downloads, cache publication and retries, real image rendering (including HEIC and EXIF rotation), slideshow waiting/cycling/exit, CLI commands, background sync startup, integer form validation and error recovery, updates between photos, control server lifecycle, automatic address selection, and timed URL overlay rendering/restoration. It uses temporary cache/token files, mocked cloud services, and SDL's dummy video/audio drivers. No `.env`, Google account, network access, or physical display is needed.

Album tests cover paginated Drive listings, ignored loose/nested photos, duplicate names, empty folders, renames, moves, updates, deletions, failed-sync recovery, and folder changes between photos while new downloads are queued. Live Google OAuth/connectivity and visible output on the target board remain manual checks; these tests do not verify the hardware graphics stack.

### Updating and transferring the installation

For an intentional package update, edit the relevant version constraint, run `uv lock --upgrade-package PACKAGE`, review the metadata/lockfile diff, and verify the unified installation before deploying it. Use `uv lock --check` to check metadata/lockfile consistency. Keep the board's `pillow_heif` and Pygame compatibility requirements in mind when changing pins. For an external tool that specifically requires a requirements file, export one from the lockfile rather than maintaining another list; for example, `uv export --locked --no-dev --no-emit-project --format requirements.txt --output-file /tmp/digitalframe-requirements.txt` exports the runtime dependencies. [uv project workflow](https://docs.astral.sh/uv/guides/projects/), [lockfile exports](https://docs.astral.sh/uv/concepts/projects/export/)

To transfer the frame, check out the same repository revision on the new machine, install its OS prerequisites and uv, select a compatible interpreter and any required declared Pygame source, supply local configuration and credentials, and synchronize the lockfile. Validate actual visible output on that machine. A startup service can eventually invoke the absolute path to `.venv/bin/digitalframe run` as the frame user, once its graphical/TTY session access is configured; startup should not resolve or install dependencies.

Docker is no longer the active deployment path. For this single-user frame, native execution keeps display and host-network access straightforward; the earlier Docker configuration remains in Git history. The local control server shares the slideshow process and runtime settings. It assumes Wi-Fi is already connected and does not manage network configuration. Automatic startup after reboot remains future work.
