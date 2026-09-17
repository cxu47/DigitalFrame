#!/usr/bin/env python3
"""Stop the runtime-only helper; Netplan remains the persistent owner."""

import os
import subprocess


def main():
    if os.geteuid() != 0:
        raise SystemExit("Run with sudo on the installed board.")
    subprocess.run(["systemctl", "stop", "digitalframe-network.service"], check=True, timeout=30)
    print("Helper stopped. Its volatile networkd override was removed and the Netplan Wi-Fi service was restored.")
    print("No boot enablement, Netplan file, firewall rule, or forwarding setting was changed.")


if __name__ == "__main__":
    main()
