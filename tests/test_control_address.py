"""Address selection without a real network or a board-specific interface name."""

import json
import socket
import subprocess
from unittest.mock import Mock

import pytest

from client.control import address


@pytest.fixture
def network(monkeypatch):
    probe = Mock()
    probe.__enter__ = Mock(return_value=probe)
    probe.__exit__ = Mock(return_value=False)
    factory = Mock(return_value=probe)
    monkeypatch.setattr(address.socket, "socket", factory)
    command = Mock(side_effect=FileNotFoundError("ip unavailable"))
    monkeypatch.setattr(address.subprocess, "run", command)
    return probe, factory, command


def test_wildcard_uses_route_address_without_sending_data(network):
    probe, factory, command = network
    probe.getsockname.return_value = ("192.168.1.42", 42100)
    assert address.control_url("0.0.0.0", 8000) == "http://192.168.1.42:8000"
    factory.assert_called_once_with(socket.AF_INET, socket.SOCK_DGRAM)
    probe.settimeout.assert_called_once_with(0.5)
    probe.send.assert_not_called()
    probe.sendto.assert_not_called()
    command.assert_not_called()
    probe.__exit__.assert_called_once()


@pytest.mark.parametrize("host,url", [
    ("192.168.20.7", "http://192.168.20.7:9000"),
    ("127.0.0.1", "http://127.0.0.1:9000"),
    ("2001:db8::7", "http://[2001:db8::7]:9000"),
])
def test_specific_bind_address_is_preserved(network, host, url):
    _, factory, _ = network
    assert address.control_url(host, 9000) == url
    factory.assert_not_called()


def test_ipv6_wildcard_uses_ipv6_route(network):
    probe, factory, _ = network
    probe.getsockname.return_value = ("fd00::42", 43100, 0, 0)
    assert address.control_url("::", 8000) == "http://[fd00::42]:8000"
    factory.assert_called_once_with(socket.AF_INET6, socket.SOCK_DGRAM)


@pytest.mark.parametrize("route_value", [None, "127.0.0.1", "0.0.0.0", "169.254.1.1", "224.0.0.1"])
def test_falls_back_to_active_interfaces_without_default_route(network, route_value):
    probe, _, command = network
    if route_value is None:
        probe.connect.side_effect = OSError("No route")
    else:
        probe.getsockname.return_value = (route_value, 43100)
    command.side_effect = None
    command.return_value.stdout = json.dumps([
        {"ifname": "lo", "addr_info": [{"local": "127.0.0.1"}]},
        {"ifname": "arbitrary-board-interface", "addr_info": [{"local": "10.0.0.42"}]},
    ])
    assert address.control_url("0.0.0.0", 8088) == "http://10.0.0.42:8088"
    assert command.call_args.kwargs["timeout"] == 1


@pytest.mark.parametrize("failure", [
    FileNotFoundError(), subprocess.TimeoutExpired("ip", 1),
    subprocess.CalledProcessError(1, "ip"),
])
def test_missing_network_or_tools_does_not_crash(network, failure):
    probe, _, command = network
    probe.connect.side_effect = OSError("No network")
    command.side_effect = failure
    assert address.control_url("0.0.0.0", 8000) is None


@pytest.mark.parametrize("output", ["invalid", "[]", "null", '[{"addr_info": null}]'])
def test_empty_or_invalid_interface_output_does_not_crash(network, output):
    probe, _, command = network
    probe.connect.side_effect = OSError("No network")
    command.side_effect = None
    command.return_value.stdout = output
    assert address.control_url("0.0.0.0", 8000) is None
