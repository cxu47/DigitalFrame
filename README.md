# DigitalFrame

DigitalFrame is a prototype for a self-updating digital photo frame. The Linux client securely connects to a third-party cloud storage provider, synchronizes images to a local cache, and displays them as a continuous slideshow.

## Motivation

This project began as a way to privately share family photos with relatives in China. Existing digital frames and cloud services did not fully meet our needs because of regional internet compatibility and privacy concerns. DigitalFrame explores a homemade alternative that can securely retrieve photos from cloud storage without requiring the recipient to manage uploads, accounts, or downloads.

A future version will run on a Raspberry Pi-style single-board computer connected to a portable display, turning the prototype into a standalone digital frame.

Although the application is intentionally simple, it also provides an opportunity to practice production-oriented software engineering skills, including client-server architecture, API development, cloud authentication, automated testing, containerization, and CI/CD. Development tasks are organized as GitHub issues, implemented on dedicated feature branches, and submitted through pull requests—even when I am both the author and reviewer—to practice a structured development and review workflow.

## Demo

![DigitalFrame demo](assets/demo.gif)

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

For a fresh desktop Linux installation, run the following from the repository root. Pygame is installed separately so that installing `requirements.txt` on an existing board does not replace its working Pygame/SDL build. The wheel command requires a wheel for your Python version and platform; it is not the recorded ARMv7 board installation procedure.

```bash
python3 -m venv .venv
source .venv/bin/activate
python -m pip install -r requirements.txt
python -m pip install --only-binary=pygame pygame==2.6.1
cp -n .env.example .env
```

For an already configured board, activate its existing environment and retain its working Pygame installation. `pillow_heif` remains pinned to 1.4.0 for the Banana Pi/Armbian compatibility adjustment. The [historical display investigation](logs/README.md) records the board's Pygame/SDL versions and a machine-specific device-selection workaround; the original Pygame build command was not recorded.

Set `GOOGLE_DRIVE_FOLDER_ID` in `.env` and place your Google OAuth client JSON at `client/secrets/google_credentials.json` with the example configuration. Create the configured cache and secrets directories if using different paths. Run `python -m client.main` from the repository root. Initial authorization prints a URL without opening a browser and waits for a callback on port 8080; the authorizing browser must be able to reach that callback (use SSH port forwarding for a remote board). The generated/refreshed token is saved in the secrets directory. Relative cache/secrets paths resolve from `client/`, credential/token filenames resolve within the secrets directory, and existing environment variables take precedence over `.env`. Timing values are seconds; `LOG_LEVEL` defaults to `INFO`.

The Dockerfile now launches the client and copies only Python source, excluding local photos and credentials from the image. Build with `docker build -t digitalframe .`. At runtime, bind-mount `.env` read-only at `/app/.env`, the cache read/write at `/app/client/cache`, and the secrets directory read/write at `/app/client/secrets` (adjust the destinations for custom paths). Perform initial authorization natively and reuse the generated token in the mounted secrets directory; the unchanged OAuth callback binds to localhost.

Displaying from a container additionally requires the host's display backend, session access, and permissions: X11/Wayland needs the corresponding environment, socket, and authorization; direct KMSDRM needs the appropriate DRM/input devices and terminal/session access. The bundled Pygame wheel may differ from the board's working SDL build. Container builds and physical display output have not been verified in the cleanup environment, where Docker's WSL integration is unavailable; the native board setup remains the reference for the archived case.
