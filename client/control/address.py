"""Find a browser URL without board-specific interface names or external services."""

from ipaddress import ip_address
import json
import socket
import subprocess


def _lan_address(value: str, version: int) -> bool:
    try:
        address = ip_address(value)
    except ValueError:
        return False
    return (address.version == version and not (
        address.is_unspecified or address.is_loopback or address.is_link_local
        or address.is_multicast
    ))


def _detect_address(version: int) -> str | None:
    family = socket.AF_INET if version == 4 else socket.AF_INET6
    destination = "192.0.2.1" if version == 4 else "2001:db8::1"
    try:
        with socket.socket(family, socket.SOCK_DGRAM) as probe:
            probe.settimeout(0.5)
            # UDP connect only selects a local route; no datagram is sent and
            # the documentation-only destination need not be reachable.
            probe.connect((destination, 9))
            address = probe.getsockname()[0]
            if _lan_address(address, version):
                return address
    except OSError:
        pass

    # A local-only LAN can have addresses without a default route. iproute2
    # is common on Linux boards; its absence does not prevent frame startup.
    try:
        result = subprocess.run(
            ["ip", "-j", f"-{version}", "address", "show", "up"],
            capture_output=True, text=True, check=True, timeout=1,
        )
        for interface in json.loads(result.stdout):
            for info in interface.get("addr_info", []):
                address = info.get("local", "")
                if _lan_address(address, version):
                    return address
    except (OSError, subprocess.SubprocessError, ValueError, TypeError, AttributeError):
        pass
    return None


def control_url(host: str, port: int) -> str | None:
    """Use the bound address, resolving wildcard listeners to a local address."""
    if host in {"0.0.0.0", "::"}:
        host = _detect_address(4 if host == "0.0.0.0" else 6)
    if not host:
        return None
    # IPv6 literals must be bracketed in browser URLs.
    authority = f"[{host}]" if ":" in host else host
    return f"http://{authority}:{port}"
