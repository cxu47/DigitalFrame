# Minimal OS migration log — 2026-09-16

Target: Banana Pi M2 Zero at `chang@192.168.1.90`.

This records changes made while validating DigitalFrame on a fresh Armbian
Minimal installation. Passwords and Wi-Fi credentials are intentionally not
recorded.

## Starting state

- Armbian community `26.11.0-trunk.44`, Debian 13 (trixie), ARMv7.
- Kernel `6.18.50-current-sunxi`; system Python `3.13.5`.
- About 452 MiB RAM, 226 MiB compressed swap, and 55 GiB free disk space.
- HDMI devices were `/dev/dri/card0`, `/dev/dri/card1`, and
  `/dev/dri/renderD128`. User `chang` was already in the `video`, `render`,
  `input`, and `audio` groups.
- The repository was clean at commit `57ff83a` on `main`.
- There was no `.env`, no cached photo, no Google credential/token, no `.venv`,
  and no `uv` executable.
- `digitalframe.service` and `digitalframe-network.service` did not exist.
- `systemd-networkd` was active and enabled. NetworkManager was not installed.
  Netplan supplied `/run/systemd/network/10-netplan-wlan0.network`, and
  `netplan-wpa-wlan0.service` plus `wpa_supplicant.service` were active.
- `wlan0` used the `brcmfmac` driver and was online on the existing `winter`
  network at `192.168.1.90`. The adapter advertised AP mode. No hotspot
  transition had been attempted at the start of the migration.

## User-level changes

Installed uv `0.12.15` for ARMv7 into:

```text
/home/chang/.local/bin/uv
/home/chang/.local/bin/uvx
```

The installer was run with `UV_NO_MODIFY_PATH=1`; it did not edit `.profile`,
`.bashrc`, or other shell/startup files.

`uv sync --locked` created `/home/chang/DigitalFrame/.venv` with Python 3.13.5
and the 53 locked project/runtime/test packages. No dependency constraint or
lockfile change was required. ARMv7 lacked compatible binary wheels for CFFI,
Pillow, Pillow-HEIF, and Pygame, so those packages were built locally.

After the first build exposed missing optional features, the cached Pillow and
Pygame build artifacts were removed with `uv cache clean pygame pillow`
(156.1 MiB of reproducible cache data) and those two packages were rebuilt.
The final builds provide:

- Pygame 2.6.1 with SDL 2.32.4 and SDL_ttf 2.24.0.
- Pillow 12.3.0 with WebP support.
- Pillow-HEIF 1.4.0 with system libheif 1.19.8 decode plugins.

No `.env` was created. Wi-Fi setup remains disabled in the ordinary application
defaults and is enabled only by the explicit manual launcher described below.

## System-level changes

`apt-get update` refreshed package indexes. The 22 packages still offered by a
normal OS upgrade were not installed as a general upgrade.

The following explicit prerequisite commands were run with
`--no-install-recommends`:

```bash
sudo apt-get install --no-install-recommends -y build-essential python3-dev libffi-dev pkg-config
sudo apt-get install --no-install-recommends -y libsdl2-dev libfreetype-dev
sudo apt-get install --no-install-recommends -y libheif-dev
sudo apt-get install --no-install-recommends -y libjpeg-dev
sudo apt-get install --no-install-recommends -y libsdl2-ttf-dev libwebp-dev
```

These pulled their normal Debian development/runtime dependencies. Apt reported
53, 148, 8, 3, and 29 new packages respectively. The large SDL dependency set
includes Mesa/DRM, Wayland, X11, audio, and input development libraries even
though DigitalFrame is intended to run directly through KMSDRM.

Installing the build and SDL prerequisites also applied repository point
updates required by those dependencies:

- `libc6`, `libc-bin`, `libc-l10n`, and `locales` to `2.41-12+deb13u4`.
- Python 3.13 runtime components to `3.13.5-2+deb13u5`.
- ALSA components to `1.2.14-1+deb13u1`.
- `libcap2`/`libcap2-bin` to `2.75-10+deb13u1+b3`.
- `libglib2.0-0t64` to `2.84.4-3~deb13u5`.
- `libpcre2-8-0` to `10.46-1~deb13u2`.

The complete package transaction is also retained by the OS in
`/var/log/apt/history.log` under the 2026-09-16 timestamps.

During the dependency setup, no package removal, kernel upgrade, reboot,
service enable/disable, getty/TTY change, boot target change, NetworkManager
installation, Netplan edit, firewall change, route change, Wi-Fi profile
change, hotspot activation, or network restart was performed. The later,
explicit runtime-only hotspot test is recorded separately below.

## Validation results

- `uv lock --check`: passed; 54 packages resolved.
- Import/version probes: Pygame 2.6.1, SDL 2.32.4, Pillow 12.3.0, and
  Pillow-HEIF 1.4.0.
- Feature probes: `pygame.font` loaded with SDL_ttf 2.24.0; Pillow WebP support
  returned true.
- Initial test run before SDL_ttf/WebP headers: 221 passed, 35 failed. Every
  failure traced to the omitted Pygame font module or Pillow WebP codec.
- Focused rerun after rebuilding: 90 passed.
- Final complete suite before the networkd work: **256 passed**, with two non-fatal warnings (Pygame was
  built without NEON optimization, and Starlette reports the existing httpx
  TestClient deprecation).
- A 15-second manual-process smoke test with SDL's dummy video/audio drivers
  initialized a 1024x768 surface, started the control server at
  `http://192.168.1.90:8000`, returned HTTP 200 locally, rendered the Slideshow,
  Wi-Fi, and Notes sections with Apply Wi-Fi disabled, and shut down cleanly.
  Wi-Fi setup was explicitly disabled for this test.

The Pygame source build took about 15 minutes on this board. Retain the uv cache
and `.venv` unless a rebuild is intentionally required.

## Runtime-only Wi-Fi helper — 2026-09-17

The optional helper was rewritten for the installed Netplan,
`systemd-networkd`, and `wpa_supplicant` stack. NetworkManager, dnsmasq, and a
firewall package were not installed. The implementation:

- scans through wpa_supplicant's Unix control socket and keeps every BSSID as a
  distinct access-point choice, including mesh satellites sharing one SSID;
- shows SSID, BSSID, channel, signal level, and security in the HTML selector;
- pins a connection attempt to the chosen BSSID;
- writes candidate station/AP configuration and the temporary priority
  networkd file only below `/run`;
- never edits `/etc/netplan`, the generated Netplan supplicant configuration,
  forwarding sysctls, firewall rules, getty settings, or boot targets; and
- stops its child supplicant, deletes volatile configuration, and restarts the
  unchanged `netplan-wpa-wlan0.service` when the helper stops.

The staging command wrote these root-owned files/directories:

```text
/opt/digitalframe-network/
/etc/digitalframe-network.json
/etc/systemd/system/digitalframe-network.service
/var/lib/digitalframe-network/
```

It also ran `systemctl daemon-reload`. The helper unit intentionally has no
`[Install]` section and reports `static`; it was never enabled. No
`digitalframe.service` exists and no `digitalframe-network.service` symlink was
created below a target `.wants` directory. The helper was started and stopped
manually during validation and is stopped at handoff.

The manual launcher is:

```bash
cd /home/chang/DigitalFrame
./deploy/run-minimal-with-wifi.sh
```

It starts the static helper, runs `uv run --no-sync digitalframe slideshow`,
and stops the helper in a shell trap. Because this fresh board has no `.env`,
the launcher supplies cache-only defaults for `CACHE_FOLDER`,
`DISPLAY_SECONDS`, and `IDLE_SECONDS`. Passing `run` remains available after
the Google/cloud settings are supplied. No shell startup file was changed.

New-image findings and fixes:

- `/sbin/wpa_cli` worked interactively but hung when invoked as a systemd child.
  The helper now speaks the wpa_supplicant Unix datagram control protocol
  directly instead of spawning `wpa_cli`.
- The first AP smoke attempt found a normal child-startup race: the private
  control socket did not yet exist. The bounded readiness loop now waits for
  socket creation; the failed attempt restored Netplan immediately.
- The initial launcher used the cloud-enabled `run` command and exposed the
  expected missing `SYNC_INTERVAL`, then the cache-only command exposed missing
  `IDLE_SECONDS`. The final launcher has the explicit cache-only defaults above;
  both failed launches still ran their cleanup trap.

Final network validation:

- The scan returned two separate `winter` radios on channel 9, BSSIDs ending
  `fb:dd` and `89:98`, at approximately -59 and -89 dBm. The regression suite
  includes a two-BSSID mesh test so they cannot be collapsed by SSID.
- A manually started helper reported `online`, `winter`, and `192.168.1.90`
  without taking ownership of the link. Netplan's supplicant stayed active and
  `/run/systemd/network/09-digitalframe.network` remained absent.
- A bounded hardware smoke test successfully entered WPA2 AP mode at
  `10.42.0.1` for 12 seconds. Its `finally` cleanup removed the runtime
  override and restored `winter` at `192.168.1.90`; the same SSH session
  resumed.
- The final launcher smoke initialized SDL dummy video at 1024x768, started the
  panel at `http://192.168.1.90:8000`, shut down cleanly on SIGINT, stopped the
  helper, and left both systemd-networkd and the Netplan supplicant active.
- The complete suite after the atomic request fix: **260 passed**; the focused
  Wi-Fi suite passed all 25 tests, with only the same
  Pygame NEON and Starlette TestClient warnings.

No home-Wi-Fi password was read, logged, or added to this file. A real
form-submitted connection attempt was not made because no test home-network
credential was supplied. Candidate credentials are not persisted: the helper
writes only a derived WPA PSK to a mode-0600 file below `/run` and deletes it
on stop/reboot. The original Netplan connection remains the reboot fallback.

At the owner's request, the separate DigitalFrame setup-hotspot password was
later changed from a generated value to the source-visible constant
`jamesbond`. This does not change the Linux/sudo password or any home-Wi-Fi
credential. The root state file was updated without printing its other fields.

Phone testing then exposed two issues: the initial scan could contain too few
BSSIDs, and a submitted WPA2 connection returned to the hotspot without a
useful failure stage. The follow-up implementation adds a **Refresh access
points** handoff that temporarily restores station mode, performs a longer full
scan, and recreates the same hotspot. Hidden and unsupported BSSIDs are shown
but disabled. The station handoff now flushes the old hotspot IPv4 state,
reapplies networkd DHCP after association, explicitly renews the lease, waits
up to 55 seconds, and reports authentication, DHCP, and internet-check failures
separately. These remain runtime-only changes below `/run`; no boot or Netplan
configuration is changed.

The helper journal showed that each reported Apply failure occurred exactly 15
seconds after submission, which is the uncommitted-reservation expiry path;
the WPA connection backend had not run. Moving Starlette's post-response
background commit into the synchronous route did not fix the physical phone
path: the separate reservation request still arrived while the follow-up
commit request did not. Apply and Refresh now use one atomic helper-socket
request that reserves and commits inside the same handler. The helper waits
five seconds before changing the radio so the HTML response can still reach
the phone. A Unix-socket integration regression test verifies that the request
leaves an operation committed rather than waiting for the 15-second expiry.

At the owner's request, the home-Wi-Fi password field now uses a visible text
input with capitalization and spellcheck disabled. The password remains absent
from responses and logs. After deployment the focused Wi-Fi suite passed all
25 tests. An installed-helper probe recognized the new operation while online,
rejected it because setup mode was inactive, and was then stopped. The helper
was left static and inactive; no boot setting or Netplan file was changed.

## Remaining physical display check

Visible KMSDRM output has not yet been launched from the physical console. A
real launch can temporarily own the active VT/display, so it should be done
only while the owner can see the HDMI screen and press Escape. The empty cache
will show DigitalFrame's waiting screen unless a test photo is added or Drive
credentials are supplied.

The runtime-only networkd backend and AP mode have now been validated. The
remaining hardware check is visible KMSDRM output and keyboard Escape handling
from the attached physical terminal. No startup automation should be added
until that manual display check is satisfactory.
