#!/usr/bin/env python3
"""Stop the helper and restore adopted NetworkManager autoconnect settings."""

import json
import os
from pathlib import Path
import subprocess


def main():
    if os.geteuid() != 0:
        raise SystemExit("Run with sudo on the installed board.")
    import dbus
    subprocess.run(["systemctl", "disable", "--now", "digitalframe.service"], check=False, timeout=20)
    subprocess.run(["systemctl", "disable", "--now", "digitalframe-network.service"], check=True, timeout=20)
    config = json.loads(Path("/etc/digitalframe-network.json").read_text())
    state = json.loads(Path("/var/lib/digitalframe-network/state.json").read_text())
    bus = dbus.SystemBus()
    nm = "org.freedesktop.NetworkManager"
    root = "/org/freedesktop/NetworkManager"
    manager = dbus.Interface(bus.get_object(nm, root), nm)
    settings = dbus.Interface(bus.get_object(nm, root + "/Settings"), nm + ".Settings")
    for path in settings.ListConnections():
        connection = dbus.Interface(bus.get_object(nm, path), nm + ".Settings.Connection")
        values = connection.GetSettings()
        identity = str(values["connection"]["uuid"])
        if identity in state.get("original_autoconnect", {}):
            values["connection"]["autoconnect"] = dbus.Boolean(state["original_autoconnect"][identity])
            connection.Update(values)
    device = manager.GetDeviceByIpIface(config["interface"])
    dbus.Interface(bus.get_object(nm, device), "org.freedesktop.DBus.Properties").Set(
        nm + ".Device", "Autoconnect", dbus.Boolean(state.get("original_device_autoconnect", True)))
    Path("/etc/NetworkManager/conf.d/99-digitalframe-connectivity.conf").unlink(missing_ok=True)
    manager.Reload(dbus.UInt32(1))
    subprocess.run(["/usr/sbin/iptables", "-w", "3", "-D", "FORWARD", "-i", config["interface"],
                    "-m", "comment", "--comment", "digitalframe-setup", "-j", "DROP"], timeout=5, check=False)
    print("Helper disabled; original autoconnect settings restored. Set WIFI_SETUP_ENABLED=false in the frame configuration.")
    print("Root-owned helper files and recovery metadata were retained for inspection. The current link was not forcibly disconnected.")


if __name__ == "__main__":
    main()
