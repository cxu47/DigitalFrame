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
    args = parser.parse_args()
    if os.geteuid() != 0:
        parser.error("Run this installer with sudo on the target board.")
    pwd.getpwnam(args.user)
    if not re.fullmatch(r"[a-zA-Z0-9_.-]{1,15}", args.interface) or not re.fullmatch(r"(?:[0-9a-fA-F]{2}:){5}[0-9a-fA-F]{2}", args.mac):
        parser.error("Invalid adapter interface or permanent MAC address.")
    import dbus
    from gi.repository import GLib  # noqa: F401 -- preflight the OS dependency
    bus = dbus.SystemBus()
    nm = "org.freedesktop.NetworkManager"
    root = "/org/freedesktop/NetworkManager"
    manager = dbus.Interface(bus.get_object(nm, root), nm)
    device = manager.GetDeviceByIpIface(args.interface)
    props = dbus.Interface(bus.get_object(nm, device), "org.freedesktop.DBus.Properties")
    wifi = props.GetAll(nm + ".Device.Wireless")
    if str(wifi["PermHwAddress"]).lower() != args.mac.lower() or int(wifi["WirelessCapabilities"]) & 0x68 != 0x68:
        parser.error("The selected adapter identity or WPA2 AP capabilities do not match.")
    for command in ("/usr/bin/curl", "/usr/sbin/dnsmasq", "/usr/sbin/iptables"):
        if not Path(command).is_file():
            parser.error(f"Missing OS dependency: {command}")
    source = Path(__file__).resolve().parents[1]
    target = Path("/opt/digitalframe-network")
    (target / "client/network").mkdir(parents=True, exist_ok=True)
    (target / "client/__init__.py").write_text("")
    for name in ("__init__.py", "state.py", "controller.py", "network_manager.py", "service.py"):
        shutil.copyfile(source / "client/network" / name, target / "client/network" / name)
    (target / "run.py").write_text(
        'import sys\nsys.path.insert(0, "/opt/digitalframe-network")\n'
        'from client.network.service import main\nmain()\n')
    for path in (target, *target.rglob("*")):
        os.chown(path, 0, 0)
        path.chmod(0o755 if path.is_dir() else 0o644)
    config = Path("/etc/digitalframe-network.json")
    config.write_text(json.dumps({"user": args.user, "interface": args.interface, "mac": args.mac}))
    config.chmod(0o600)
    nm_config = Path("/etc/NetworkManager/conf.d/99-digitalframe-connectivity.conf")
    nm_config.write_text("# Managed by DigitalFrame: the helper checks only while online.\n[connectivity]\ninterval=0\n")
    nm_config.chmod(0o644)
    shutil.copyfile(source / "deploy/digitalframe-network.service", "/etc/systemd/system/digitalframe-network.service")
    manager.Reload(dbus.UInt32(1))
    run("systemctl", "daemon-reload")
    print("Helper files installed. No services were started or enabled; existing service enablement is unchanged.")
    print("Hotspot hardware validation is paused. Keep WIFI_SETUP_ENABLED=false and launch the slideshow manually.")
    print("See docs/board-recovery.md to recover a board with the earlier services already enabled.")


if __name__ == "__main__":
    main()
