#!/usr/bin/env python3
"""Stage the experimental helper without starting services or enabling boot startup."""

import argparse
import json
import os
from pathlib import Path
import pwd
import re
import shutil
import subprocess


def run(*args):
    subprocess.run(args, check=True, timeout=20)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--user", required=True)
    parser.add_argument("--interface", required=True)
    parser.add_argument("--mac", required=True)
    parser.add_argument("--country", required=True,
                        help="Two-letter ISO Wi-Fi regulatory country, for example CN or US")
    args = parser.parse_args()
    if os.geteuid() != 0:
        parser.error("Run this installer with sudo on the target board.")
    pwd.getpwnam(args.user)
    if not re.fullmatch(r"[a-zA-Z0-9_.-]{1,15}", args.interface) or not re.fullmatch(r"(?:[0-9a-fA-F]{2}:){5}[0-9a-fA-F]{2}", args.mac):
        parser.error("Invalid adapter interface or permanent MAC address.")
    country = args.country.strip().upper()
    if not re.fullmatch(r"[A-Z]{2}", country):
        parser.error("Country must be a two-letter ISO Wi-Fi regulatory code such as CN or US.")
    actual_mac = Path(f"/sys/class/net/{args.interface}/address")
    if not actual_mac.is_file() or actual_mac.read_text().strip().lower() != args.mac.lower():
        parser.error("The selected adapter identity does not match.")
    for command in ("/usr/bin/ip", "/usr/bin/networkctl", "/usr/bin/systemctl",
                    "/usr/sbin/iw", "/sbin/wpa_supplicant"):
        if not Path(command).is_file():
            parser.error(f"Missing OS dependency: {command}")
    modes = subprocess.run(["/usr/sbin/iw", "phy"], check=True, capture_output=True, text=True, timeout=10).stdout
    if "* AP" not in modes:
        parser.error("The selected adapter does not advertise access-point mode.")
    enabled = subprocess.run(["systemctl", "is-enabled", "digitalframe-network.service"],
                             capture_output=True, text=True, timeout=10)
    if enabled.stdout.strip() == "enabled":
        parser.error("Refusing to replace an enabled helper. Disable it explicitly first.")
    source = Path(__file__).resolve().parents[1]
    target = Path("/opt/digitalframe-network")
    (target / "client/network").mkdir(parents=True, exist_ok=True)
    (target / "client/__init__.py").write_text("")
    for name in ("__init__.py", "state.py", "controller.py", "networkd.py", "service.py"):
        shutil.copyfile(source / "client/network" / name, target / "client/network" / name)
    (target / "run.py").write_text(
        'import sys\nsys.path.insert(0, "/opt/digitalframe-network")\n'
        'from client.network.service import main\nmain()\n')
    for path in (target, *target.rglob("*")):
        os.chown(path, 0, 0)
        path.chmod(0o755 if path.is_dir() else 0o644)
    config = Path("/etc/digitalframe-network.json")
    config.write_text(json.dumps({
        "user": args.user, "interface": args.interface,
        "mac": args.mac, "country": country,
    }))
    config.chmod(0o600)
    shutil.copyfile(source / "deploy/digitalframe-network.service", "/etc/systemd/system/digitalframe-network.service")
    run("systemctl", "daemon-reload")
    print("Helper staged as a static unit. No service was started or enabled and Netplan was not edited.")
    print("Launch with deploy/run-minimal-with-wifi.sh; stopping it restores the Netplan-owned link.")


if __name__ == "__main__":
    main()
