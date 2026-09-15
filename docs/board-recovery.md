# Recover local board control

Status, 2026-09-15: hardware hotspot testing is paused. The board is unplugged. No more board or startup changes are authorized; these are options for the owner to perform if chosen. Repository changes alone do not repair an already-installed service.

## What was installed

The deployment installed `/etc/systemd/system/digitalframe.service` and `/etc/systemd/system/digitalframe-network.service`, then ran:

```bash
sudo systemctl enable --now digitalframe-network.service digitalframe.service
```

That created boot links under `/etc/systemd/system/multi-user.target.wants/`. The frame ran as `chang`, using the existing `.venv`, with `StandardInput=tty`, `TTYPath=/dev/tty1`, `Conflicts=getty@tty1.service`, and `Restart=on-failure`. It occupied the first console in place of its login prompt. Esc exits the app but does not start a shell or bring the conflicting getty back. Ctrl+C/Z cannot control a shell that is not running there. A separate systemd console-lock stall was also observed; its role in the later failure could not be verified.

The privileged helper was copied into `/opt/digitalframe-network`, with configuration at `/etc/digitalframe-network.json` and state at `/var/lib/digitalframe-network/state.json`. It disabled adopted Wi-Fi profiles' and the device's autoconnect flags, recording the originals in its state file. Offline waiting survives reboot, so reboot alone does not resume normal home-Wi-Fi retries. It also installed `/etc/NetworkManager/conf.d/99-digitalframe-connectivity.conf` and an AP forwarding rule. The board's `.env` was set to `WIFI_SETUP_ENABLED=true` and `CONTROL_HOST=0.0.0.0`.

The requested replacement hotspot password was **not applied** before SSH was lost. Hotspot discovery succeeded, but phone authentication and recovery were not validated. Passing automated tests did not establish hardware reliability.

## Option 1: a different local console

After powering on, try **Ctrl+Alt+F2** (or F3) with the board's physical keyboard. This may open an independent login prompt. It can fail if the OS console/service manager is stalled; do not keep repeating hung commands.

If login works and you choose to undo DigitalFrame's boot setup, run these as separate commands:

```bash
sudo timeout 20s systemctl disable --now digitalframe.service digitalframe-network.service
sudo timeout 10s systemctl start getty@tty1.service
sudo nmcli --wait 30 connection up winter
hostname -I
```

Check the first command succeeded before attempting Wi-Fi recovery; the helper must be stopped so it cannot switch back to the AP. `winter` is this board's known saved home profile. A timeout means this path has failed: proceed to offline SD recovery rather than assuming services stopped. The timeout limits waiting; it does not guarantee cancellation of a systemd job already submitted.

With a working console and service manager, `sudo /usr/bin/python3 /home/chang/DigitalFrame/deploy/remove-network-helper.py` restores the recorded pre-install autoconnect flags and removes the helper's connectivity override/forwarding rule. That script disables the two services as an explicit rollback. Alternatively, leave home Wi-Fi activation manual with `nmcli`; do not enable autoconnect unless you want it.

Set `WIFI_SETUP_ENABLED=false` in `/home/chang/DigitalFrame/.env`. For later cached playback, launch from a logged-in terminal:

```bash
cd /home/chang/DigitalFrame
WIFI_SETUP_ENABLED=false .venv/bin/python -m client slideshow
```

Preserve the working board-specific SDL configuration. This command does not install/start a system service or manage Wi-Fi. Esc should return to the shell that launched it; this needs physical verification before further hotspot testing.

## Option 2: disable the two boot services from the SD card

This avoids the broken board console and preserves the OS and application files. Use another Linux system (a live Linux USB is sufficient), mount the card's **Linux root filesystem**, and locate its `etc`, `home`, and `var` directories. A Windows-visible boot partition alone is not enough. Do not format the card if Windows cannot read it. WSL access to a USB SD reader depends on the host/reader setup; do not assume that inserting the card makes its Linux filesystem available.

In the following command `/mnt/frame-root` must be the mounted **board SD root**, not the development machine's `/`. Verify that `/mnt/frame-root/home/chang/DigitalFrame` and the two unit files exist first:

```bash
sudo systemctl --root=/mnt/frame-root disable digitalframe.service digitalframe-network.service
```

`--root` makes this a filesystem operation on the card, without contacting the board's running systemd. Do not add `--now`. Confirm both boot links are absent from the card's `etc/systemd/system/multi-user.target.wants/` directory before booting it. This removes their boot activation; it does not delete the unit files or restore all NetworkManager settings. [systemctl documentation](https://github.com/systemd/systemd/blob/main/man/systemctl.xml)

Edit the card's `home/chang/DigitalFrame/.env` to set `WIFI_SETUP_ENABLED=false`. Remove only the helper-owned `etc/NetworkManager/conf.d/99-digitalframe-connectivity.conf` if restoring NetworkManager's earlier connectivity-check configuration. Unmount/eject cleanly, return the card, and boot. The frame should no longer take over tty1. Wi-Fi profile autoconnect may still be disabled; use the local terminal and `sudo nmcli --wait 30 connection up winter` to reconnect manually. Complete the recorded-state rollback above later if desired.

This undoes DigitalFrame's boot activation; it cannot guarantee recovery from an independent OS/serial-console problem. If no console is available afterward, retain the card for inspection and use a fresh image on another card.

## Option 3: reinstall a minimal image

Using a spare card preserves the current installation for comparison and recovery. Before overwriting the existing card, save the board's `.env`, Google OAuth client/token files in `client/secrets/` (or its configured secrets directory), and any custom SDL/Pygame build notes and scripts. Keep credentials private. Photos can be downloaded again from Google Drive; no local image backup is needed. An old `.venv` should not be transplanted blindly across OS/Python versions.

The [official Banana Pi M2 Zero download page](https://armbian.com/boards/bananapim2zero) currently lists a Debian 13 Minimal (CLI) image as a community rolling build. Recheck that page when downloading. A minimal OS is suitable for the already-demonstrated direct KMSDRM display path, but does not by itself fix the Wi-Fi driver/hotspot problem. Validate the graphics dependencies and manual terminal launch on the new image.

Armbian's current minimal images normally use `systemd-networkd`, while CLI/desktop images use NetworkManager. Our helper explicitly requires NetworkManager, so it is not compatible with an untouched minimal installation. Keep hotspot setup disabled and use that image's documented network configuration initially; choose a single network manager deliberately before any future hotspot work. [Armbian networking](https://docs.armbian.com/user-guide/networking/)

First verify HDMI login, manual Wi-Fi configuration, SSH, and manual cached playback. Keep the desktop/startup/service configuration under the owner's control. Do not run the helper installer or enable DigitalFrame boot services as part of basic setup.
