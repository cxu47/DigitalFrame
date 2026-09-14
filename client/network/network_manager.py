"""NetworkManager D-Bus backend, loaded only by the installed board helper.

Uses the board's python3-dbus/GLib packages. No credentials enter a shell or argv.
"""

from ipaddress import ip_address, ip_network
import json
import subprocess
import time
import uuid

from .state import NetworkError

NM = "org.freedesktop.NetworkManager"
ROOT = "/org/freedesktop/NetworkManager"
PROPS = "org.freedesktop.DBus.Properties"
DEVICE = NM + ".Device"
WIRELESS = DEVICE + ".Wireless"
CONNECTION = NM + ".Settings.Connection"
ACTIVE = NM + ".Connection.Active"


def select_subnet(prefixes, preferred=""):
    occupied = []
    for prefix in prefixes:
        try:
            network = ip_network(prefix, strict=False)
            if network.version == 4 and network.prefixlen:
                occupied.append(network)
        except ValueError:
            continue
    candidates = [f"10.42.{i}.0/24" for i in range(32)] + ["172.30.240.0/24", "192.168.240.0/24"]
    if preferred:
        preferred = str(ip_network(preferred + "/24", strict=False))
        if preferred in candidates:
            candidates.remove(preferred)
            candidates.insert(0, preferred)
    for candidate in candidates:
        network = ip_network(candidate)
        if not any(network.overlaps(other) for other in occupied):
            return str(network.network_address + 1)
    raise NetworkError("No non-overlapping hotspot subnet is available.")


class NetworkManager:
    def __init__(self, interface, mac):
        self.interface, self.mac = interface, mac.lower()
        self.bus = None
        self.device = None
        self.ap_uuid = None

    def obj(self, path):
        return self.bus.get_object(NM, path)

    def iface(self, path, interface):
        return self.dbus.Interface(self.obj(path), interface)

    def props(self, path, interface):
        return self.iface(path, PROPS).GetAll(interface, timeout=5)

    def profiles(self):
        return self.iface(ROOT + "/Settings", NM + ".Settings").ListConnections(timeout=5)

    def settings(self, path):
        return self.iface(path, CONNECTION).GetSettings(timeout=5)

    def profile(self, identity):
        for path in self.profiles():
            if str(self.settings(path)["connection"]["uuid"]) == identity:
                return path
        return None

    def prepare(self, store):
        import dbus
        self.dbus = dbus
        if self.bus is None:
            self.bus = dbus.SystemBus(private=True)
        self.device = self.iface(ROOT, NM).GetDeviceByIpIface(self.interface, timeout=5)
        wifi = self.props(self.device, WIRELESS)
        if str(wifi["PermHwAddress"]).lower() != self.mac:
            raise NetworkError("The configured Wi-Fi adapter identity does not match.")
        # AP, RSN, CCMP: never downgrade the setup network to WEP/open.
        if int(wifi["WirelessCapabilities"]) & 0x68 != 0x68:
            raise NetworkError("The Wi-Fi adapter does not support a WPA2 access point.")
        if not self.props(ROOT, NM)["WirelessHardwareEnabled"]:
            raise NetworkError("The Wi-Fi adapter is blocked by hardware.")
        self.iface(ROOT, PROPS).Set(NM, "WirelessEnabled", dbus.Boolean(True), timeout=5)
        data = store.data
        self.ap_uuid = data.setdefault("ap_uuid", str(uuid.uuid4()))
        device_info = self.props(self.device, DEVICE)
        data.setdefault("original_device_autoconnect", bool(device_info.get("Autoconnect", True)))
        active = str(device_info.get("ActiveConnection", "/"))
        if active != "/" and not data.get("saved_uuid"):
            active_info = self.props(active, ACTIVE)
            if active_info.get("Uuid") != self.ap_uuid:
                data["saved_uuid"] = str(active_info["Uuid"])
        originals = data.setdefault("original_autoconnect", {})
        # Record changes first, so uninstall can restore even a partial setup.
        for path in self.profiles():
            settings = self.settings(path)
            connection = settings["connection"]
            if connection.get("type") != "802-11-wireless":
                continue
            if connection.get("interface-name", self.interface) != self.interface:
                continue
            bound = settings.get("802-11-wireless", {}).get("mac-address")
            if bound and bytes(bound).hex() != self.mac.replace(":", ""):
                continue
            identity = str(connection["uuid"])
            if not str(connection.get("id", "")).startswith("DigitalFrame "):
                originals.setdefault(identity, bool(connection.get("autoconnect", True)))
            store.save()
            if connection.get("autoconnect", True):
                connection["autoconnect"] = dbus.Boolean(False)
                self.iface(path, CONNECTION).Update(settings, timeout=5)
        self.iface(self.device, PROPS).Set(DEVICE, "Autoconnect", dbus.Boolean(False), timeout=5)
        store.save()
        abandoned = data.pop("candidate_uuid", None)
        if abandoned and abandoned != data.get("saved_uuid"):
            path = self.profile(abandoned)
            if path:
                self.iface(path, CONNECTION).Delete(timeout=5)
            store.save()

    def upstream(self):
        for active in self.props(ROOT, NM)["ActiveConnections"]:
            info = self.props(active, ACTIVE)
            if int(info["State"]) != 2 or not info.get("Default") or info.get("Uuid") == self.ap_uuid:
                continue
            for device in info["Devices"]:
                dev = self.props(device, DEVICE)
                ip4 = str(dev.get("Ip4Config", "/"))
                if ip4 == "/":
                    continue
                addresses = self.props(ip4, NM + ".IP4Config").get("AddressData", [])
                for entry in addresses:
                    address = str(entry["address"])
                    if ip_address(address).is_loopback or ip_address(address).is_link_local:
                        continue
                    ssid = "Ethernet"
                    if int(dev["DeviceType"]) == 2:
                        settings = self.settings(info["Connection"])
                        ssid = bytes(settings["802-11-wireless"]["ssid"]).decode("utf-8", "replace")
                    return {"address": address, "ssid": ssid, "interface": str(dev["Interface"])}
        return None

    def verify_upstream(self):
        info = self.upstream()
        if not info:
            return None
        # curl bounds DNS as well as TCP/TLS. Never follow a captive-portal redirect.
        probes = [("https://connectivitycheck.gstatic.com/generate_204", b"", b"204"),
                  ("https://www.msftconnecttest.com/connecttest.txt", b"Microsoft Connect Test", b"200")]
        for url, expected, status in probes:
            try:
                result = subprocess.run([
                    "/usr/bin/curl", "--silent", "--noproxy", "*", "--ipv4",
                    "--interface", info["interface"], "--max-time", "4", "--connect-timeout", "3",
                    "--max-filesize", "512", "--proto", "=https", "--write-out", "\n%{http_code}", url,
                ], stdout=subprocess.PIPE, stderr=subprocess.DEVNULL, timeout=5, check=False)
                if result.returncode == 0:
                    body, code = result.stdout.rsplit(b"\n", 1)
                    if code == status and body.strip() == expected:
                        return info
            except (OSError, ValueError, subprocess.SubprocessError):
                pass
        return None

    def activate(self, path, timeout=45):
        active = self.iface(ROOT, NM).ActivateConnection(path, self.device, "/", timeout=5)
        deadline = time.monotonic() + timeout
        while time.monotonic() < deadline:
            state = int(self.props(active, ACTIVE)["State"])
            if state == 2:
                return active
            if state == 4:
                break
            time.sleep(.25)
        try:
            self.iface(ROOT, NM).DeactivateConnection(active, timeout=5)
        except Exception:
            pass
        raise NetworkError("Wi-Fi activation failed or timed out.")

    def activate_saved(self, identity):
        path = self.profile(identity)
        if path is not None:
            self.activate(path)

    def connection_settings(self, identity, ssid, password, *, address=None):
        d = self.dbus
        wifi = {"ssid": d.ByteArray(ssid.encode("utf-8")), "mode": "ap" if address else "infrastructure",
                "mac-address": d.ByteArray(bytes.fromhex(self.mac.replace(":", "")))}
        if address:
            wifi.update(band="bg", channel=d.UInt32(6))
        ipv4 = {"method": "shared" if address else "auto"}
        if address:
            ipv4.update({"address-data": d.Array([d.Dictionary({"address": address, "prefix": d.UInt32(24)}, signature="sv")], signature="a{sv}"),
                         "never-default": d.Boolean(True)})
        else:
            ipv4["dhcp-timeout"] = d.Int32(30)
        sections = {
            "connection": {"id": "DigitalFrame hotspot" if address else "DigitalFrame Wi-Fi",
                           "uuid": identity, "type": "802-11-wireless", "interface-name": self.interface,
                           "autoconnect": d.Boolean(False), "auth-retries": d.Int32(1)},
            "802-11-wireless": wifi,
            "802-11-wireless-security": {"key-mgmt": "wpa-psk", "psk": password,
                                         "proto": d.Array(["rsn"], signature="s")},
            "ipv4": ipv4, "ipv6": {"method": "disabled"},
        }
        if address:
            sections["802-11-wireless-security"].update(
                pairwise=d.Array(["ccmp"], signature="s"), group=d.Array(["ccmp"], signature="s"))
        return d.Dictionary({name: d.Dictionary(values, signature="sv") for name, values in sections.items()}, signature="sa{sv}")

    def ap_running(self):
        active = str(self.props(self.device, DEVICE).get("ActiveConnection", "/"))
        return active != "/" and self.props(active, ACTIVE).get("Uuid") == self.ap_uuid and int(self.props(active, ACTIVE)["State"]) == 2

    def block_forwarding(self, active):
        # Restrict only traffic forwarded from this radio during setup. Host
        # traffic (DHCP, SSH, HTTP) and unrelated firewall rules remain intact.
        rule = ["FORWARD", "-i", self.interface, "-m", "comment", "--comment", "digitalframe-setup", "-j", "DROP"]
        check = subprocess.run(["/usr/sbin/iptables", "-w", "3", "-C", *rule],
                               stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, timeout=5)
        if active and check.returncode != 0:
            subprocess.run(["/usr/sbin/iptables", "-w", "3", "-I", *rule], check=True,
                           stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, timeout=5)
        elif not active and check.returncode == 0:
            subprocess.run(["/usr/sbin/iptables", "-w", "3", "-D", *rule], check=True,
                           stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, timeout=5)

    def ensure_access_point(self, store):
        self.block_forwarding(True)
        if self.ap_running():
            ip4 = self.props(self.device, DEVICE)["Ip4Config"]
            return str(self.props(ip4, NM + ".IP4Config")["AddressData"][0]["address"])
        result = subprocess.run(["ip", "-j", "-4", "route", "show", "table", "all"],
                                capture_output=True, text=True, check=True, timeout=5)
        prefixes = [route.get("dst", "") for route in json.loads(result.stdout)]
        for path in self.profiles():
            settings = self.settings(path)
            if settings["connection"]["uuid"] == self.ap_uuid:
                continue
            for address in settings.get("ipv4", {}).get("address-data", []):
                prefixes.append(f"{address['address']}/{address['prefix']}")
        prefixes.extend(store.data.get("upstream_prefixes", []))
        address = select_subnet(prefixes, store.data.get("ap_address", ""))
        settings = self.connection_settings(self.ap_uuid, store.data["ap_ssid"], store.data["ap_password"], address=address)
        path = self.profile(self.ap_uuid)
        if path:
            self.iface(path, CONNECTION).Update(settings, timeout=5)
        else:
            path = self.iface(ROOT + "/Settings", NM + ".Settings").AddConnection(settings, timeout=5)
        # Preserve upstream prefixes for the next activation after the route disappears.
        store.data["upstream_prefixes"] = sorted({str(p) for p in prefixes if p and p != "default"})
        store.save()
        self.activate(path, timeout=30)
        ip4 = self.props(self.device, DEVICE)["Ip4Config"]
        actual = str(self.props(ip4, NM + ".IP4Config")["AddressData"][0]["address"])
        if actual != address:
            raise NetworkError("Hotspot address did not match its assigned subnet.")
        return actual

    def connect(self, ssid, password, store):
        identity = str(uuid.uuid4())
        store.data["candidate_uuid"] = identity
        store.save()
        path = self.iface(ROOT + "/Settings", NM + ".Settings").AddConnectionUnsaved(
            self.connection_settings(identity, ssid, password), timeout=5)
        success = False
        try:
            self.activate(path, timeout=40)
            info = self.verify_upstream()
            if info and info["interface"] == self.interface:
                self.iface(path, CONNECTION).Save(timeout=5)
                self.block_forwarding(False)
                store.data["saved_uuid"] = identity
                store.data.pop("candidate_uuid", None)
                store.save()
                success = True
                return info
        except Exception:
            pass  # Driver errors can contain credentials. Only sanitized outcomes leave this backend.
        finally:
            if not success:
                self.iface(path, CONNECTION).Delete(timeout=5)
        return None
