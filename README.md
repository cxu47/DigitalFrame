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
- Local photo caching
- Temporary download files to prevent incomplete images from being displayed
- Continuous slideshow using Pygame and Pillow
- Configurable image display duration through `DISPLAY_SECONDS`
- Automatic EXIF orientation correction
- Graceful handling of missing or invalid cached images
- Waiting screen when no cached photos are available

## Important Limitations

- Cached files are currently identified by filename rather than file content.
- If two remote files have the same name, synchronization skips later files once that filename exists in the cache. Updated remote content under an existing filename is also skipped.
- Remote deletion reconciliation is not yet implemented. Removing a photo from the cloud does not currently remove its cached copy automatically.
- The project is currently a prototype and has not undergone a complete security review.
- Google Drive requests use the Google API client's transport timeout behavior; the application does not configure its own request timeout.

## Potential Upgrades

- Randomized slideshow order
- Collage layouts
- Encrypted local storage
- Improved authentication and security protocols
- Configurable overwrite and duplicate-handling policies
- Cache validation during startup
- Automatic removal of locally cached photos deleted from the cloud
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
- [ ] Reconcile remote deletions with the local cache

### Phase 3 - Alibaba Cloud OSS Integration

- [ ] Evaluate Alibaba Cloud OSS compatibility
- [ ] Configure secure long-term authentication
- [ ] Confirm token and credential expiration behavior
- [ ] Implement OSS photo listing and downloading
- [ ] Test connectivity from both the United States and China

### Phase 4 - Hardware Deployment

- [ ] Deploy the client on a Raspberry Pi-style device
- [ ] Connect and configure a portable display
- [ ] Configure automatic startup after reboot
- [ ] Test unattended synchronization and recovery
- [ ] Assemble the components into a standalone frame enclosure

## Project Status

DigitalFrame is under active development. The current implementation demonstrates the core workflow of authenticating with cloud storage, synchronizing photos into a local cache, and displaying them as a continuously updating slideshow.

### Installation and configuration

DigitalFrame runs natively as the intended Linux user. Install [uv](https://docs.astral.sh/uv/getting-started/installation/) and a compatible Python interpreter (declared range: 3.12–3.14). The uv workflow was validated with uv 0.12.13 and Python 3.12.3 on Linux AArch64; the archived ARMv7/Python 3.14 board still needs migration verification. uv manages Python packages; the OS still supplies display drivers, session/device access, and any native SDL/image libraries needed by your chosen build.

Run these commands from the repository root for a **fresh standard display installation**:

```bash
uv sync --locked --no-dev --extra display
cp -n .env.example .env
```

The `display` extra installs Pygame 2.6.1 from the locked source. A compatible wheel or build environment must exist for the selected Python/platform. `pillow_heif` remains pinned to 1.4.0 for the earlier Banana Pi/Armbian compatibility adjustment. The `dev` group is excluded from runtime installation.

For an **existing board with a working Pygame/SDL build**, first validate the migration in a separate checkout/environment. Then use its existing interpreter and retain the separately provisioned Pygame installation. For example, if its base interpreter is `/usr/bin/python3.14`:

```bash
uv sync --locked --no-dev --inexact --python /usr/bin/python3.14 --no-python-downloads
```

Replace that interpreter path with the one actually used by the board's environment. This command is intended for an environment that already contains the working Pygame build; it does not recreate that build in a fresh environment. Do not enable the `display` extra on this profile. Plain `uv sync` removes undeclared packages, while `--inexact` retains them unless they conflict with declared requirements. [uv synchronization behavior](https://docs.astral.sh/uv/concepts/projects/sync/)

The [historical display investigation](logs/README.md) records the board's interpreter, Pygame/SDL versions, and device-selection workaround. Its original Pygame build command is unknown, so this profile has a documented reproducibility gap: the lockfile alone cannot reproduce the custom graphics stack. Record the build procedure, artifact hash, and interpreter ABI when provisioning another board. A copied laptop `.venv` is not a deployment method.

In `.env`, confirm `GOOGLE_DRIVE_FOLDER_ID` and place the Google OAuth client JSON at `client/secrets/google_credentials.json` for the example configuration. Create cache/secrets directories if using custom paths. Relative paths resolve from `client/`, credential/token filenames resolve within the secrets directory, and existing environment variables override `.env`. Timing values are seconds; `LOG_LEVEL` defaults to `INFO`.

### Running the frame

The Typer CLI provides these commands after installation:

```bash
uv run --no-sync digitalframe run        # Initial sync, background sync, slideshow
uv run --no-sync digitalframe slideshow  # Cached photos only; no cloud access
uv run --no-sync digitalframe sync       # One sync; no display required
uv run --no-sync digitalframe --help
```

Pygame must be installed through one of the display profiles for `run` and `slideshow`. Help needs no `.env` or display dependencies; no arguments show help. For a cache-only slideshow, ensure the configured cache directory exists first. Exit the slideshow with Escape or by closing its window.

Initial Drive authorization prints a URL without opening a browser and waits for a localhost callback on port 8080. The authorizing browser must reach that callback; use SSH port forwarding when authorizing a remote board. Tokens are created/refreshed in the configured secrets directory. The `slideshow` command does not initiate authorization.

`--no-sync` keeps normal startup separate from package changes. After installation, `.venv/bin/digitalframe` runs the same commands directly. `python -m client` exposes the same CLI in the selected environment; the existing `python -m client.main`, `python -m client.slideshow`, and `python -m client.sync` entry points still work. Installation is editable from this checkout; keep the checkout available and run from its root. Standalone wheel deployment with relocated configuration/data is not supported by this workflow.

### Maintenance and deployment

`pyproject.toml` declares direct dependencies and profiles; the generated `uv.lock` fixes their resolved versions. `requirements.txt` is no longer maintained. Install development tooling with `uv sync --locked --extra display` on a standard environment, or `uv sync --locked --inexact --python /path/to/board/python --no-python-downloads` on a board with separately provisioned Pygame. The existing tests are outside the scope of this migration.

For an intentional package update, edit the relevant version constraint, run `uv lock --upgrade-package PACKAGE`, review the metadata/lockfile diff, and verify the selected profile before deploying it. Use `uv lock --check` to check metadata/lockfile consistency. Keep the board's `pillow_heif` and Pygame compatibility requirements in mind when changing pins. For an external tool that specifically requires a requirements file, export one from the lockfile rather than maintaining another list; for example, `uv export --locked --no-dev --extra display --no-emit-project --format requirements.txt --output-file /tmp/digitalframe-requirements.txt` exports the standard profile's dependencies. [uv project workflow](https://docs.astral.sh/uv/guides/projects/), [lockfile exports](https://docs.astral.sh/uv/concepts/projects/export/)

To transfer the frame, check out the same repository revision on the new machine, install its OS prerequisites and uv, select a compatible interpreter/display profile, supply local configuration and credentials, and synchronize the lockfile. Validate actual visible output on that machine. A startup service can eventually invoke the absolute path to `.venv/bin/digitalframe run` as the frame user, once its graphical/TTY session access is configured; startup should not resolve or install dependencies.

Docker is no longer the active deployment path. For this single-user frame, native execution keeps display and host-network access straightforward; the earlier Docker configuration remains in Git history. A future local control server can share application/configuration functions without launching another slideshow or requiring containers. Wi-Fi control will need an adapter to the host's network manager and its authorization model. No server or automatic-startup service is introduced by this migration.
