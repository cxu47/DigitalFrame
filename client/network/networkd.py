"""Runtime-only systemd-networkd/wpa_supplicant backend for minimal Armbian.

The operating system's Netplan files are never edited.  When a setup hotspot or
candidate station is needed, this backend installs a higher-priority networkd
file below /run and runs its own wpa_supplicant child.  Stopping the helper (or
rebooting, because /run is volatile) restores the Netplan-owned connection.
"""

from hashlib import pbkdf2_hmac
from ipaddress import ip_address, ip_network
import json
import os
from pathlib import Path
import re
import socket
import subprocess
import threading
import time

from .state import NetworkError


WPA_SUPPLICANT = "/sbin/wpa_supplicant"
IP = "/usr/bin/ip"
NETWORKCTL = "/usr/bin/networkctl"
SYSTEMCTL = "/usr/bin/systemctl"
IW = "/usr/sbin/iw"


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
        try:
            preferred_network = str(ip_network(preferred + "/24", strict=False))
        except ValueError:
            preferred_network = ""
        if preferred_network in candidates:
            candidates.remove(preferred_network)
            candidates.insert(0, preferred_network)
    for candidate in candidates:
        network = ip_network(candidate)
        if not any(network.overlaps(other) for other in occupied):
            return str(network.network_address + 1)
    raise NetworkError("No non-overlapping hotspot subnet is available.")


def frequency_channel(frequency):
    if frequency == 2484:
        return 14
    if 2412 <= frequency <= 2472:
        return (frequency - 2407) // 5
    if 5000 <= frequency <= 5900:
        return (frequency - 5000) // 5
    return 0


def parse_scan_results(output):
    """Keep every radio/BSSID; do not merge mesh nodes sharing an SSID."""
    points = []
    seen = set()
    for line in output.splitlines()[1:]:
        fields = line.split("\t", 4)
        if len(fields) != 5:
            continue
        bssid, frequency, signal, flags, ssid = fields
        bssid = bssid.lower()
        if bssid in seen or not re.fullmatch(r"(?:[0-9a-f]{2}:){5}[0-9a-f]{2}", bssid):
            continue
        try:
            frequency_value, signal_value = int(frequency), int(signal)
        except ValueError:
            continue
        visible_ssid = ssid or "Hidden network"
        supported = bool(ssid) and "PSK" in flags and "WEP" not in flags
        if "SAE" in flags and "PSK" not in flags:
            security = "WPA3 (not yet supported)"
        elif "WPA2" in flags or "RSN" in flags:
            security = "WPA2"
        elif "WPA" in flags:
            security = "WPA"
        elif "WEP" in flags:
            security = "WEP (not supported)"
        else:
            security = "Open (not supported)"
        seen.add(bssid)
        points.append({
            "bssid": bssid,
            "ssid": visible_ssid,
            "signal": signal_value,
            "channel": frequency_channel(frequency_value),
            "security": security,
            "supported": supported,
        })
    return tuple(sorted(points, key=lambda point: (-point["signal"], point["ssid"], point["bssid"])))


def _psk(ssid, password):
    if re.fullmatch(r"[0-9a-fA-F]{64}", password):
        return password.lower()
    return pbkdf2_hmac("sha1", password.encode("ascii"), ssid.encode("utf-8"), 4096, 32).hex()


class Networkd:
    def __init__(self, interface, mac, country, *, runtime="/run/digitalframe-network",
                 network_file="/run/systemd/network/09-digitalframe.network"):
        self.interface, self.mac = interface, mac.lower()
        country = str(country).strip().upper()
        if not re.fullmatch(r"[A-Z]{2}", country):
            raise NetworkError("The Wi-Fi regulatory country must be a two-letter code.")
        self.country = country
        self.runtime = Path(runtime)
        self.network_file = Path(network_file)
        self.process = None
        self.mode = None
        self.owns_link = False
        self.last_failure = ""

    def _run(self, args, *, timeout=10, check=True, **kwargs):
        return subprocess.run(args, timeout=timeout, check=check, **kwargs)

    def _write(self, path, value, mode=0o600):
        path = Path(path)
        fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, mode)
        with os.fdopen(fd, "w") as target:
            target.write(value)
            target.flush()
            os.fsync(target.fileno())
        path.chmod(mode)

    @property
    def netplan_service(self):
        return f"netplan-wpa-{self.interface}.service"

    @property
    def control_dir(self):
        return self.runtime / "wpa"

    def prepare(self, store):
        actual = Path(f"/sys/class/net/{self.interface}/address").read_text().strip().lower()
        if actual != self.mac:
            raise NetworkError("The configured Wi-Fi adapter identity does not match.")
        for command in (WPA_SUPPLICANT, IP, NETWORKCTL, SYSTEMCTL, IW):
            if not Path(command).is_file():
                raise NetworkError("A required minimal-OS networking command is unavailable.")
        modes = self._run([IW, "phy"], capture_output=True, text=True).stdout
        if "* AP" not in modes:
            raise NetworkError("The Wi-Fi adapter does not advertise access-point mode.")
        self.runtime.mkdir(parents=True, exist_ok=True, mode=0o750)

    def _control(self, command, *, helper=None, timeout=5):
        use_helper = self.process is not None if helper is None else helper
        server = (self.control_dir if use_helper else Path("/run/wpa_supplicant")) / self.interface
        client = self.runtime / f"control-{os.getpid()}-{threading.get_ident()}"
        client.unlink(missing_ok=True)
        control = socket.socket(socket.AF_UNIX, socket.SOCK_DGRAM)
        try:
            control.settimeout(timeout)
            control.bind(str(client))
            control.connect(str(server))
            control.send(command.encode("ascii"))
            return control.recv(65535).decode("utf-8", "replace")
        finally:
            control.close()
            client.unlink(missing_ok=True)

    def _status(self, *, helper=None, timeout=5):
        output = self._control("STATUS", helper=helper, timeout=timeout)
        return dict(line.split("=", 1) for line in output.splitlines() if "=" in line)

    def _address_info(self, status, *, timeout=5):
        if status.get("wpa_state") != "COMPLETED" or status.get("mode", "station") != "station":
            return None
        result = self._run([IP, "-j", "-4", "address", "show", "dev", self.interface],
                           capture_output=True, text=True, timeout=timeout)
        for link in json.loads(result.stdout):
            for entry in link.get("addr_info", []):
                address = entry.get("local", "")
                try:
                    parsed = ip_address(address)
                except ValueError:
                    continue
                if entry.get("scope") == "global" and not parsed.is_link_local:
                    return {"address": address, "ssid": status.get("ssid", "Wi-Fi"), "interface": self.interface}
        return None

    def upstream(self, *, timeout=5):
        return self._address_info(self._status(timeout=timeout), timeout=timeout)

    def scan_access_points(self):
        helper = self.owns_link
        if helper:
            if self.mode != "station" or self.process is None or self.process.poll() is not None:
                return ()
            # Stop the failed association before asking this supplicant to scan.
            try:
                self._control("DISCONNECT", helper=True)
            except OSError:
                pass
        deadline = time.monotonic() + 10
        while True:
            try:
                try:
                    self._control("BSS_FLUSH 0", helper=helper)
                except OSError:
                    pass
                if self._control("SCAN", helper=helper).startswith("OK"):
                    break
            except OSError:
                pass
            if time.monotonic() >= deadline:
                return ()
            time.sleep(.5)
        best = ()
        for _ in range(16):
            time.sleep(.5)
            try:
                parsed = parse_scan_results(self._control("SCAN_RESULTS", helper=helper))
            except OSError:
                continue
            # scan_results can initially return the previous scan.  Keep
            # polling for the full bounded interval so slower satellites are
            # not omitted merely because one cached BSSID was already present.
            if len(parsed) >= len(best):
                best = parsed
        return best

    def _routes(self):
        result = self._run([IP, "-j", "-4", "route", "show", "table", "all"],
                           capture_output=True, text=True, timeout=5)
        return [route.get("dst", "") for route in json.loads(result.stdout)]

    def _stop_process(self):
        process, self.process = self.process, None
        if process is None:
            return
        process.terminate()
        try:
            process.wait(timeout=5)
        except subprocess.TimeoutExpired:
            process.kill()
            process.wait(timeout=2)

    def _flush_ipv4(self):
        self._run([IP, "-4", "address", "flush", "dev", self.interface],
                  timeout=5, check=False, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        self._run([IP, "-4", "route", "flush", "dev", self.interface],
                  timeout=5, check=False, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)

    def _take_link(self, network):
        if not self.owns_link:
            self._run([SYSTEMCTL, "stop", self.netplan_service], timeout=15)
            self.owns_link = True
        self._stop_process()
        self._flush_ipv4()
        self._write(self.network_file, network, 0o644)
        self._run([NETWORKCTL, "reload"], timeout=10)
        self._run([NETWORKCTL, "reconfigure", self.interface], timeout=15)
        self._run([IP, "link", "set", "dev", self.interface, "up"], timeout=5)

    def _start_supplicant(self, config, mode):
        self.control_dir.mkdir(parents=True, exist_ok=True, mode=0o700)
        config_path = self.runtime / f"{mode}.conf"
        self._write(config_path, config)
        self.process = subprocess.Popen(
            [WPA_SUPPLICANT, "-Dnl80211", "-i", self.interface, "-c", str(config_path)],
            stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
        )
        self.mode = mode

    def ap_running(self):
        return self.mode == "ap" and self.process is not None and self.process.poll() is None

    def block_forwarding(self, active):
        # The minimal image already has IPv4 forwarding disabled.  We do not
        # alter sysctls or firewall rules; networkd only serves this local /24.
        return None

    def ensure_access_point(self, store):
        if self.ap_running():
            return store.data.get("ap_address", "10.42.0.1")
        prefixes = self._routes() + list(store.data.get("upstream_prefixes", ()))
        address = select_subnet(prefixes, store.data.get("ap_address", ""))
        store.data["upstream_prefixes"] = sorted({prefix for prefix in prefixes if prefix and prefix != "default"})
        store.save()
        network = (
            "[Match]\n" f"Name={self.interface}\n\n"
            "[Network]\n" f"Address={address}/24\n" "DHCPServer=yes\nIPv6AcceptRA=no\nLinkLocalAddressing=no\nIPForward=no\n\n"
            "[DHCPServer]\nPoolOffset=10\nPoolSize=100\nEmitDNS=no\nEmitRouter=yes\n"
        )
        self._take_link(network)
        config = (
            f"ctrl_interface={self.control_dir}\ncountry={self.country}\nap_scan=2\n"
            "network={\n" f"  ssid={store.data['ap_ssid'].encode('utf-8').hex()}\n"
            "  mode=2\n  frequency=2437\n  key_mgmt=WPA-PSK\n  proto=RSN\n"
            "  pairwise=CCMP\n  group=CCMP\n" f"  psk={_psk(store.data['ap_ssid'], store.data['ap_password'])}\n" "}\n"
        )
        self._start_supplicant(config, "ap")
        deadline = time.monotonic() + 15
        while time.monotonic() < deadline:
            if self.process.poll() is not None:
                break
            try:
                if self._status(helper=True).get("mode") == "AP":
                    return address
            except OSError:
                # The child creates its control socket after process startup.
                pass
            time.sleep(.25)
        raise NetworkError("The setup hotspot did not start.")

    def connect(self, ssid, bssid, password, store):
        self.last_failure = "Could not connect. Check the password or choose another access point."
        psk = _psk(ssid, password)
        network = (
            "[Match]\n" f"Name={self.interface}\n\n"
            "[Network]\nDHCP=yes\nLinkLocalAddressing=ipv6\n\n"
            "[DHCP]\nRouteMetric=600\nUseMTU=true\n"
        )
        self._take_link(network)
        config = (
            f"ctrl_interface={self.control_dir}\ncountry={self.country}\n"
            "network={\n" f"  ssid={ssid.encode('utf-8').hex()}\n  bssid={bssid}\n"
            "  key_mgmt=WPA-PSK\n  proto=RSN\n  pairwise=CCMP\n  group=CCMP\n"
            f"  psk={psk}\n" "}\n"
        )
        self._start_supplicant(config, "station")
        deadline = time.monotonic() + 55
        associated = False
        got_address = False
        dhcp_started = False
        while time.monotonic() < deadline:
            if self.process.poll() is not None:
                self.last_failure = "The Wi-Fi driver ended the connection attempt. Choose another access point and try again."
                break
            try:
                status = self._status(helper=True)
                if status.get("wpa_state") == "COMPLETED" and status.get("mode", "station") == "station":
                    associated = True
                    if not dhcp_started:
                        # Reapply the DHCP network after carrier/association;
                        # this avoids retaining the hotspot address and makes
                        # networkd immediately request a fresh lease.
                        self._run([NETWORKCTL, "reconfigure", self.interface], timeout=15, check=False)
                        self._run([NETWORKCTL, "renew", self.interface], timeout=15, check=False)
                        dhcp_started = True
                    info = self._address_info(status)
                else:
                    info = None
                if info:
                    got_address = True
                    self.last_failure = ""
                    previous = store.data.get("saved_network")
                    store.data["saved_network"] = {"ssid": ssid, "psk": psk}
                    try:
                        store.save()
                    except OSError:
                        if previous is None:
                            store.data.pop("saved_network", None)
                        else:
                            store.data["saved_network"] = previous
                        info["saved"] = False
                    return info
            except OSError:
                # Association cannot be queried until the child has created
                # its private control socket.
                pass
            time.sleep(.5)
        if not associated:
            self.last_failure = (
                "Could not authenticate with that access point. Check the password or choose a different BSSID.")
        elif not got_address:
            self.last_failure = (
                "Wi-Fi authentication succeeded, but the router did not provide an IP address (DHCP). Try another access point.")
        return None

    def activate_saved(self, identity):
        """Offer a successful control-panel network to Netplan's supplicant."""
        try:
            self._run([SYSTEMCTL, "start", self.netplan_service], timeout=5, check=False)
        except (OSError, subprocess.TimeoutExpired):
            pass  # The caller still checks whether Netplan has connected.
        try:
            return self._offer_saved_profile(identity)
        finally:
            # An OS profile may also be saved; connect if currently disconnected.
            try:
                self._control("RECONNECT", helper=False, timeout=1)
            except OSError:
                pass

    def _offer_saved_profile(self, identity):
        if not isinstance(identity, dict):
            return False
        ssid, psk = identity.get("ssid"), identity.get("psk")
        try:
            ssid_bytes = ssid.encode("utf-8") if isinstance(ssid, str) else b""
        except UnicodeError:
            ssid_bytes = b""
        if not 1 <= len(ssid_bytes) <= 32 or any(ord(character) < 32 for character in ssid) or (
            not isinstance(psk, str) or not re.fullmatch(r"[0-9a-fA-F]{64}", psk)
        ):
            return False
        deadline = time.monotonic() + 3
        network_id = None
        while network_id is None:
            try:
                response = self._control("ADD_NETWORK", helper=False, timeout=1).strip()
                if not response.isdecimal():
                    return False
                network_id = response
            except OSError:
                if time.monotonic() >= deadline:
                    return False
                time.sleep(.25)
        settings = (
            ("ssid", ssid_bytes.hex()),
            ("psk", psk.lower()),
            ("key_mgmt", "WPA-PSK"),
            ("proto", "RSN"),
            ("pairwise", "CCMP"),
            ("group", "CCMP"),
            ("priority", "1"),
        )
        enabled = False
        try:
            for name, value in settings:
                if not self._control(f"SET_NETWORK {network_id} {name} {value}",
                                     helper=False, timeout=1).startswith("OK"):
                    return False
            enabled = self._control(f"ENABLE_NETWORK {network_id}",
                                    helper=False, timeout=1).startswith("OK")
            return enabled
        except OSError:
            return False
        finally:
            if not enabled:
                try:
                    self._control(f"REMOVE_NETWORK {network_id}", helper=False, timeout=1)
                except OSError:
                    pass

    def restore(self):
        """Return ownership to the unchanged Netplan service."""
        if not self.owns_link:
            return
        self._stop_process()
        self.mode = None
        self.network_file.unlink(missing_ok=True)
        for path in self.runtime.glob("*.conf"):
            path.unlink(missing_ok=True)
        self._run([NETWORKCTL, "reload"], timeout=10, check=False)
        self._flush_ipv4()
        self._run([SYSTEMCTL, "start", self.netplan_service], timeout=15, check=False)
        self._run([NETWORKCTL, "reconfigure", self.interface], timeout=15, check=False)
        self.owns_link = False
