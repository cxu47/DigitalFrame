#!/usr/bin/env python3
"""Install the reviewed helper into root-owned paths on a dedicated NetworkManager board."""

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
    parser.add_argument("--start", action="store_true", help="Enable and start the installed helper")
    parser.add_argument("--project", help="Also install the ordinary-user frame service on tty1, using this prepared checkout")
    args = parser.parse_args()
    if os.geteuid() != 0:
        parser.error("Run this installer with sudo on the target board.")
    pwd.getpwnam(args.user)
    if not re.fullmatch(r"[a-zA-Z0-9_.-]{1,15}", args.interface) or not re.fullmatch(r"(?:[0-9a-fA-F]{2}:){5}[0-9a-fA-F]{2}", args.mac):
        parser.error("Invalid adapter interface or permanent MAC address.")
    if args.project:
        project = str(Path(args.project).resolve())
        if not re.fullmatch(r"/[a-zA-Z0-9_./-]+", project) or not re.fullmatch(r"[a-zA-Z0-9_-]+", args.user):
            parser.error("Use a project path and username without spaces or special characters for the service.")
        if not (Path(project) / ".venv/bin/python").is_file() or not (Path(project) / "client/network/client.py").is_file():
            parser.error("Prepare the updated checkout and its existing runtime environment before installing the frame service.")
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
    if args.project:
        unit = (source / "deploy/digitalframe.service").read_text().replace("@USER@", args.user).replace("@PROJECT@", project)
        Path("/etc/systemd/system/digitalframe.service").write_text(unit)
    manager.Reload(dbus.UInt32(1))
    run("systemctl", "daemon-reload")
    if args.start:
        run("systemctl", "enable", "digitalframe-network.service")
        run("systemctl", "restart", "digitalframe-network.service")
        if args.project:
            run("systemctl", "enable", "digitalframe.service")
            run("systemctl", "restart", "digitalframe.service")
    print("Helper installed. Enable WIFI_SETUP_ENABLED=true and CONTROL_HOST=0.0.0.0 in the frame's configuration.")


if __name__ == "__main__":
    main()
