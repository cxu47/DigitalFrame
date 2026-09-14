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
- Background synchronization at a configurable interval, with cached playback available during network outages
- Newly downloaded photos play next after the current photo finishes, without renaming files
- One-level photo albums mirrored in the local cache, with an All/folder selector
- Drive metadata and content checksums detect additions, edits, moves, renames, deletions, and cache corruption
- Temporary download files to prevent incomplete images from being displayed
- Continuous slideshow using Pygame and Pillow, with one upcoming image prepared in a worker
- Configurable image display duration through `DISPLAY_SECONDS` and a plain HTML control panel on the local Wi-Fi
- Automatic EXIF orientation correction
- Fullscreen display at the current screen resolution, with proportional photo scaling and centered black bars
- Graceful handling of missing or invalid cached images
- Waiting screen when no cached photos are available

## Important Limitations

- Only photos directly inside immediate child folders are included. Loose root photos, deeper nested folders, and Drive shortcuts are ignored.
- A process lock permits one sync per cache directory. Album photos in that directory are disposable copies of Drive; a successful sync removes album photos absent from Drive. Legacy loose root photos and unrelated non-photo files are left in place.
- The project is currently a prototype and has not undergone a complete security review.
- A slow image decode can still extend a photo interval if the next image is not ready in time. The current photo stays visible while loading finishes; keyboard handling and notifications continue.

## Potential Upgrades

- Randomized slideshow order
- Collage layouts
- Encrypted local storage
- Improved authentication and security protocols
- Configurable overwrite and duplicate-handling policies
- User-configurable cloud provider or server URL

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

In `.env`, confirm `GOOGLE_DRIVE_FOLDER_ID` and place the Google OAuth client JSON at `client/secrets/google_credentials.json` for the example configuration. Create cache/secrets directories if using custom paths. Relative paths resolve from `client/`, credential/token filenames resolve within the secrets directory, and existing environment variables override `.env`. Timing values are seconds; `DISPLAY_SECONDS` must be a positive integer (for example `5`, not `5.0`). `IDLE_SECONDS`, `SYNC_INTERVAL`, and `NETWORK_TIMEOUT` accept finite decimal values of at least 0.001 seconds. `NETWORK_TIMEOUT` defaults to 10 seconds per HTTP operation. Configuration is checked per command: cache-only playback needs no Google credentials or sync interval, and one-shot sync needs no display/control settings. `LOG_LEVEL` defaults to `INFO`.

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

Initial Drive authorization prints a URL without opening a browser and waits up to 60 seconds for a localhost callback on port 8080; a timeout is reported and retried by background sync. The authorizing browser must reach that callback; use SSH port forwarding when authorizing a remote board. Tokens are created/refreshed in the configured secrets directory. The `slideshow` command does not initiate authorization.

`--no-sync` keeps normal startup separate from package changes. After installation, `.venv/bin/digitalframe` runs the same commands directly. `python -m client` exposes the same CLI in the selected environment; the existing `python -m client.main`, `python -m client.slideshow`, and `python -m client.sync` entry points still work. Installation is editable from this checkout; keep the checkout available and run from its root. Standalone wheel deployment with relocated configuration/data is not supported by this workflow.

During `digitalframe run`, each successfully downloaded photo enters a shared in-memory queue as soon as its complete file is published to the cache. The current photo finishes its configured interval, then queued photos play in download-completion order before the regular newest-first rotation resumes where it left off. Each sync downloads newer uploads first across all albums. Photos promoted from that rotation are skipped at their original position for the current cycle. Ordinary filenames and photo metadata stay unchanged; duplicate or unsafe filenames are adjusted as described below. Failed downloads are not queued; unreadable images are skipped. Already cached files are not promoted again on every sync.

New arrivals are detected on the next sync, controlled by `SYNC_INTERVAL`; this is polling, not a live Google Drive notification. Initial sync starts in a worker alongside cached playback, so the slideshow can open before authorization or downloads finish. Initial downloads are queued as they complete. The queue lasts for the current `run` process. A separate `digitalframe sync` process does not send priority notifications to a cache-only `slideshow` process; those files join its ordinary rotation on the next cache scan.

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

Regular playback starts with the newest photo, both across **All** albums and within a selected folder. Ordering uses Google's `createdTime`: when the file was created in Drive, normally its initial upload time, rather than the camera's capture date, last edit time, or local download time. Saved timestamps keep this order available during offline restarts. Equal timestamps use alphabetical path order; photos without valid creation metadata play last, alphabetically. Existing caches gain creation timestamps on their next successful sync without downloading unchanged image bytes again.

Every sync fetches all listing pages for the parent and its immediate albums, using one Google Drive connection for that pass. Only supported photo extensions are downloaded. After a complete listing, it hashes the actual cached bytes and compares them to current Drive MD5 checksums. Unchanged bytes need no download. Zero-byte files, wrong photos under existing names, and other mismatches are automatically replaced from Drive. If Drive omits a checksum, the file is downloaded again rather than trusting a previous manifest. Available remote file sizes are also checked before publication. See Google's [file metadata](https://developers.google.com/workspace/drive/api/reference/rest/v3/files) and [paginated listings](https://developers.google.com/workspace/drive/api/reference/rest/v3/files/list).

The `.photos.json` manifest records the last successful remote catalog and its SHA-256 metadata hash. It is not used as proof that a local file is correct. A missing, corrupt, or outdated manifest is rebuilt from Drive; recovery never restores image backups. Renames and moves can reuse existing bytes only after their checksum matches current Drive metadata. Temporary hard links avoid copying full images while filenames are swapped, and abandoned staging directories are cleaned up on a later sync.

Downloads stay in temporary files until their checksums and sizes pass validation. Listing failures leave cached photos intact. Failed downloads retain existing files and defer deletion cleanup until a fully successful pass. A successful sync removes supported photos inside immediate cache subfolders when they are absent from Drive, then removes empty obsolete album directories. This also reconciles stale photos when the old manifest is missing. Keep personal originals outside the cache. Duplicate names within a folder get distinct suffixes, unsafe path components are normalized, and long photo names preserve their supported extension.

A `.sync.lock` file prevents another process from syncing the same cache concurrently; leave the lock file in place. `digitalframe sync` returns a nonzero exit code for lock, configuration, listing, or download failures. Shutdown signals the sync worker to stop between file/chunk operations and joins it for up to five seconds. Network operations have a timeout; an operation still in progress can finish in its daemon thread or be interrupted when the process exits. The next successful sync rechecks the actual bytes against Drive.

New-photo priority respects the selected album. Photos from other albums join the normal rotation when you select that album or All. If the selected album disappears or is renamed during sync, selection falls back to All. An existing but empty selected album shows the waiting screen. Album listings refresh at most once per second, and after completed sync passes.

While a photo is visible, a single worker prepares the next image, including the first photo of the next cycle. Pillow decoding and resizing happen on that worker; all Pygame drawing stays on the display thread. Only one upcoming image is prepared at a time, with its retained RGB pixels sized for the display. Folder changes and newly queued photos are checked at photo boundaries. A conflicting decode is allowed to finish before its result is discarded. If sync replaces a file while it is loading, the new version is prepared again. Timer sleeps stop at the remaining photo interval.

Unreadable photos are skipped and reported on the control page. The same unchanged failed file is retried after 60 seconds, or sooner when sync replaces it. If no photo is readable, playback waits instead of repeatedly decoding files without a delay. Sync can repair local corruption from Drive; if the original on Drive is itself unreadable, the error remains until the source is corrected.

### Control the frame from another device

Assume the frame and your phone, tablet, or computer are already connected to the same Wi-Fi, with device-to-device traffic allowed. When `run` or `slideshow` starts, the frame detects its network address and logs the browser URL, for example **`http://192.168.1.42:8000`**. Open the displayed URL on the other device. `CONTROL_HOST` defaults to `0.0.0.0` (listen on network interfaces), and `CONTROL_PORT` defaults to `8000`; the browser uses the actual frame IP, not `0.0.0.0` or the other device's `localhost`.

The URL also appears at the **top-left of the slideshow for 30 seconds**, including on the waiting screen when no photos are cached. Set `CONTROL_URL_DISPLAY_SECONDS` in `.env` to change this duration; it accepts nonnegative whole seconds, with `0` disabling the overlay. The countdown begins when the control URL becomes available to the slideshow. The overlay disappears during a long photo interval without advancing or reloading the photo. This startup setting is separate from the photo duration controlled by the form.

Address detection uses the operating system's route-selected local address, with a fallback to active Linux interfaces when no route is available. It does not hard-code a board model or interface name, send a probe datagram, or require internet access. An explicit `CONTROL_HOST` uses that listener's address. If detection fails, the server continues with a warning and no URL overlay; check the board's network settings or router device list. A background supervisor rechecks the address every 15 seconds and announces a changed URL on the slideshow. On machines with several networks or a VPN, the selected route may belong to another network; bind `CONTROL_HOST` to the desired local address if needed.

Enter positive whole seconds and click **Apply**. The page uses a normal HTML form, without JavaScript or internet assets; error history uses a simple red text style. The server accepts integer text such as `5`, validates it, and redirects back to the page with the updated duration. Letters, blanks, decimal notation such as `5.0`, fractions, zero, and negative values show an error directly below the form. Invalid submissions preserve the active setting and keep the slideshow running; correct the input and submit again.

Use the **Photo folder** dropdown and **Apply folder** to choose an album or **All**. This is a second plain HTML form. Each option includes its cached picture count and latest available Drive date, for example `kids — 24 pictures — updated 2026-09-12`. **All** totals the picture counts and shows the latest date across the albums. Dates are in UTC and use the latest creation/modification timestamp for the folder or its currently cached photos, not the time of the last sync check. Counts include supported files directly inside cache albums, including files awaiting repair; loose, nested, and temporary files are excluded. Empty folders show zero pictures. Missing metadata shows `updated unknown` until a successful sync supplies it. Refresh the page after a sync to see updated details and added, renamed, or removed albums.

Each accepted duration Apply action shows **“Seconds per photo: …” for 15 seconds** in the same top-left banner. **Apply folder** shows **“Photo folder: …”** for the same duration, including when All is selected or the same folder is submitted again. If sync removes the selected folder, the automatic fallback also shows **“Photo folder: All”**. It replaces any visible startup URL; the latest accepted duration or folder submission replaces the message and restarts the 15-second timer. Invalid submissions do not trigger a message. Setting confirmations still appear when the startup URL overlay is disabled.

Changes apply starting with the next successfully displayed photo. The current photo finishes its original interval. Settings live in memory: restarting restores `DISPLAY_SECONDS` from configuration and selects All folders. Refreshing the page displays the current setting. The panel and initial cloud sync start independently of playback. The panel also works in cache-only mode without internet access. The `sync` command does not start it.

The panel is intended for a trusted local network and has no login. Wi-Fi setup is available with the optional board helper described below. Escape, window close, or Ctrl+C stops the panel with the display. An unavailable port or unexpected server exit is logged while cached playback continues. The supervisor retries the same configured address and port every 15 seconds; it does not automatically choose a different port. Run one application process; a separate Uvicorn process or multiple workers would not share these runtime settings. Google authorization continues to use its separate port 8080.

Without the board helper, network/SSL connection failures and a missing network address show **“Network connection problem. Retrying...” in red at the top-left of the slideshow**. The warning stays across photo changes until the affected connection checks recover, even when the startup URL overlay is disabled. It takes priority over temporary URL and settings messages; settings still apply normally. Cached playback and background retries continue. These network errors are omitted from the control page, including after recovery, and remain in the console logs.

Other sync, image, and control-server errors appear **in red below the controls**, with UTC timestamps and active/recovered labels. Refresh the page to see updates. The bounded history resets when the app restarts. A disconnected Wi-Fi link or failed listener can make the page unreachable until connectivity/listening recovers. TLS verification remains enabled.

### Offline hotspot and Wi-Fi setup

The HTML panel has **Slideshow control**, **Wi-Fi control**, and **Notes** sections. With the board helper enabled, loss of internet starts a WPA2 setup hotspot. The slideshow displays the hotspot name, setup password, and current control URL in a red multiline banner **without a timeout**, including when `CONTROL_URL_DISPLAY_SECONDS=0`. It stays through every photo and failed connection attempt until internet connectivity is restored. The setup password is separate from the home-Wi-Fi password; home credentials are never displayed or logged.

Join the displayed DigitalFrame network on your phone, stay connected despite its “No internet” warning, and open the displayed `http://…:8000` address. The same folder and duration forms control the running cached slideshow. Enter your home **Wi-Fi SSID** and **Wi-Fi password**, then select **Apply Wi-Fi**. This first version supports WPA2-Personal and compatible transition networks. Credentials are preserved exactly, validated on the server, and sent through a restricted local helper socket to NetworkManager. No captive portal, JavaScript polling, or internet assets are needed.

The single radio temporarily leaves hotspot mode during one bounded connection attempt. On failure, it restores the same hotspot credentials and waits for another submission. On success, reconnect your phone to home Wi-Fi and open the new URL shown on HDMI. The form remains visible while online, with read-only inputs and a disabled submit button. Refresh the page to see a changed state. A stale page cannot bypass the server-side restriction.

**Offline means no periodic internet checks, Drive requests, or automatic home-Wi-Fi retries.** The waiting state survives app/helper/board restarts. The helper checks connectivity only while online (every 30 seconds, with short request deadlines) and after a user-submitted attempt. It also receives local device events. A separate cloud outage or authorization error does not cause a hotspot when independent internet checks succeed. Normal Drive sync resumes once after reconnection and then uses its usual interval. Local listener/helper supervision can still recover a crashed service; that is separate from internet reconnection.

The helper chooses a private subnet avoiding known local routes and remembered upstream prefixes; it prefers `10.42.0.1/24` when available. That address is an example, not a guarantee. The displayed URL uses the actual AP/upstream interface and listener port. Phone-side routes cannot be exhaustively checked. AP forwarding is blocked while setup is active; the network provides local board access rather than a router service.

Install only on a dedicated Linux board whose adapter and driver support WPA2 AP mode and whose Wi-Fi is owned by NetworkManager. The helper uses OS `python3-dbus`, `python3-gi`, `curl`, `dnsmasq`, and `iptables`; it does not modify the frame's custom Pygame environment. The app itself remains unprivileged. The installer copies only helper code to root-owned `/opt/digitalframe-network`, creates a restricted socket service, and disables NetworkManager's separate periodic connectivity checker. The helper records adopted profiles' original autoconnect flags before disabling automatic station retries; it does not delete those profiles.

After updating the board checkout and verifying its existing runtime, set these values in its `.env`:

```dotenv
WIFI_SETUP_ENABLED=true
CONTROL_HOST=0.0.0.0
```

For the investigated board, the explicit installation command is:

```bash
sudo /usr/bin/python3 deploy/install-network-helper.py \
  --user chang --interface wlan0 --mac ac:6a:a3:29:b9:61 \
  --project /home/chang/DigitalFrame --start
```

Replace these identifiers with the target board's verified values. `--project` installs an ordinary-user slideshow service on tty1, alongside the helper, so setup instructions and the panel can return after reboot. It replaces the tty1 login prompt while running; use SSH or another console for administration. Preserve the board's existing SDL device configuration. Omitting `--start` stages installation; omitting `--project` installs only the helper for a manually managed frame process. Keep the display/panel operational before conducting a live outage test. A single-radio hotspot switch disconnects Wi-Fi SSH, so keep local console access during installation.

Service status and logs:

```bash
systemctl status digitalframe digitalframe-network
journalctl -u digitalframe -u digitalframe-network
```

To disable the managed setup, run `sudo /usr/bin/python3 deploy/remove-network-helper.py`, then set `WIFI_SETUP_ENABLED=false`. It disables both installed services, restores recorded autoconnect flags and the normal connectivity-check configuration, and removes only its own forwarding rule. Helper files and state are retained for inspection. To manually recover SSH from a local board console, stop `digitalframe-network` and explicitly activate the saved home connection with `sudo nmcli connection up <profile-name>`; the helper must be stopped first because its waiting-for-user state is intentional.

### Maintenance and deployment

`pyproject.toml` declares runtime dependencies and the development group; the generated `uv.lock` fixes their resolved versions. `requirements.txt` is no longer maintained. Install runtime packages and development tooling together with `uv sync --locked`. Resolve any board-specific Pygame source as described above before migrating that board.

### Automated tests

After installing development tooling and Pygame, run from the repository root:

```bash
uv run --no-sync python -m pytest -q
```

The suite checks the main workflows: saved/refreshed/new Drive authorization, photo listing and chunked downloads, cache publication and retries, real image rendering (including HEIC and EXIF rotation), slideshow waiting/cycling/exit, CLI commands, nonblocking background sync startup, integer form validation and error recovery, updates between photos, control server lifecycle, automatic address selection, and timed URL overlay rendering/restoration. It uses temporary cache/token files, mocked cloud services, and SDL's dummy video/audio drivers. No `.env`, Google account, network access, or physical display is needed.

Album tests cover paginated Drive listings, ignored loose/nested photos, duplicate names, empty folders, renames, moves, updates, deletions, failed-sync recovery, and folder changes between photos while new downloads are queued. Additional tests cover actual preload threads and cycle boundaries, corrupted/wrong cache bytes, interrupted sync recovery, process locking, SSL failures, server restarts, and escaped red error history. Live Google OAuth/connectivity and visible output on the target board remain manual checks; these tests do not verify the hardware graphics stack.

### Updating and transferring the installation

For an intentional package update, edit the relevant version constraint, run `uv lock --upgrade-package PACKAGE`, review the metadata/lockfile diff, and verify the unified installation before deploying it. Use `uv lock --check` to check metadata/lockfile consistency. Keep the board's `pillow_heif` and Pygame compatibility requirements in mind when changing pins. For an external tool that specifically requires a requirements file, export one from the lockfile rather than maintaining another list; for example, `uv export --locked --no-dev --no-emit-project --format requirements.txt --output-file /tmp/digitalframe-requirements.txt` exports the runtime dependencies. [uv project workflow](https://docs.astral.sh/uv/guides/projects/), [lockfile exports](https://docs.astral.sh/uv/concepts/projects/export/)

To transfer the frame, check out the same repository revision on the new machine, install its OS prerequisites and uv, select a compatible interpreter and any required declared Pygame source, supply local configuration and credentials, and synchronize the lockfile. Validate actual visible output on that machine. A startup service can eventually invoke the absolute path to `.venv/bin/digitalframe run` as the frame user, once its graphical/TTY session access is configured; startup should not resolve or install dependencies.

Docker is no longer the active deployment path. For this single-user frame, native execution keeps display and host-network access straightforward; the earlier Docker configuration remains in Git history. The local control server shares the slideshow process and runtime settings. Optional board networking and systemd startup are described in the hotspot installation section; ordinary development runs leave network management disabled.
