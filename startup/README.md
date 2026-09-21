# Reviewed console startup

No file in this directory runs automatically from the repository. Review all
five configuration files, then run the one installer explicitly on the frame:

```bash
sudo /bin/bash /home/chang/DigitalFrame/startup/install-startup.sh CN
```

The installer stages files but does not start, stop, enable, disable, restart,
or reboot anything. Its preflight is intentionally specific to the inspected
board: user `chang` (UID 1000), `/home/chang/DigitalFrame`, `wlan0`, permanent
MAC `ac:6a:a3:29:b9:61`, `multi-user.target`, and the already-enabled tty1
getty. A mismatch stops the install instead of guessing.
Replace `CN` with the two-letter Wi-Fi regulatory country where the board is
physically operated (`US` for a board in the United States); the same country
is used by the setup hotspot and the later home-Wi-Fi connection.

## Boot and exit behavior

On the next reboot, the existing `getty@tty1.service` automatically logs in as
`chang`. `/etc/profile.d/digitalframe-console.sh` recognizes only that physical
tty and calls the repository launcher in the foreground. SSH, the serial getty,
and other VTs are unaffected.

The launcher starts the static Wi-Fi helper, then runs the same full
`digitalframe run` command used manually, with package synchronization disabled
at boot. It overrides `WIFI_SETUP_ENABLED=true` and `CONTROL_HOST=0.0.0.0` only
for this process; it does not edit `.env`. The current helper policy always
opens the setup hotspot and asks the user to select Wi-Fi, even when the OS has
a saved network. Cloud sync waits while offline and cached playback continues.

The launcher is deliberately not `exec`'d. Its exit trap stops the helper and
restores the unchanged Netplan-owned connection. Pressing Ctrl-C, Escape, or
`q`, or closing/exiting the application, therefore returns to the login shell
on tty1. The application is not automatically restarted during that login.

## Service scope

The installation does not add or enable a DigitalFrame application service.
It does not change the default target or touch current masks/disablement,
including `alsa-utils.service`, `systemd-networkd-wait-online.service`, and
`x11-common.service`. `digitalframe-network.service` has no `[Install]` section
and remains static; the foreground launcher starts and stops it on demand.

The sudoers fragment does not remove or replace `chang`'s existing
`(ALL : ALL) ALL` access. It adds passwordless permission only for the exact
helper start and stop commands so unattended login cannot block on a password
prompt. Automatic tty1 login means anyone with physical console access gets a
`chang` shell after the app exits; that is required for the requested fallback.
