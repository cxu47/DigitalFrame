"""Offline Wi-Fi policy, credential handling, sync gating and persistent HDMI instructions."""

from dataclasses import replace
import json
import os
import re
from threading import Event, Thread
from unittest.mock import Mock, call

from fastapi.testclient import TestClient
import pytest

from client.network.client import NetworkClient
from client.network.controller import NetworkController, SETUP_HOTSPOT_PASSWORD, StateFile
from client.network.networkd import Networkd, parse_scan_results, select_subnet
from client.network import networkd
from client.network.service import Handler, Server
from client.network.state import NetworkError, NetworkSnapshot, validate_credentials
from client.control.app import create_app
from client.control.page import render_page
from client.settings import RuntimeSettings


@pytest.fixture
def recovery(tmp_path):
    backend = Mock()
    backend.upstream.return_value = None
    backend.ensure_access_point.return_value = "10.42.0.1"
    backend.ap_running.return_value = True
    backend.connect.return_value = None
    backend.last_failure = ""
    backend.scan_access_points.return_value = (
        {"ssid": "home", "bssid": "02:00:00:00:00:01", "signal": -45,
         "channel": 6, "security": "WPA2", "supported": True},
        {"ssid": "home", "bssid": "02:00:00:00:00:02", "signal": -70,
         "channel": 11, "security": "WPA2", "supported": True},
    )
    store = StateFile(tmp_path / "network.json")
    clock = [100.0]
    controller = NetworkController(backend, store, clock=lambda: clock[0],
                                   saved_connection_seconds=0)
    return controller, backend, store, clock


def test_offline_remains_idle_across_hours_events_and_restart(recovery):
    controller, backend, store, clock = recovery
    controller.start()
    assert controller.snapshot.can_submit
    assert controller.snapshot.ap_password == SETUP_HOTSPOT_PASSWORD == "jamesbond"
    credentials = (controller.snapshot.ap_ssid, controller.snapshot.ap_password)
    assert store.data["waiting"]
    backend.reset_mock()
    clock[0] += 100000
    controller.step()
    backend.upstream.assert_not_called()
    backend.ensure_access_point.assert_not_called()
    controller.event()
    controller.step()
    backend.ap_running.assert_called_once()
    backend.upstream.assert_not_called()
    backend.connect.assert_not_called()
    new = NetworkController(backend, StateFile(store.path), saved_connection_seconds=0)
    new.start()
    assert new.snapshot.can_submit
    assert (new.snapshot.ap_ssid, new.snapshot.ap_password) == credentials
    backend.activate_saved.assert_called_once_with(None)
    backend.upstream.assert_called_once_with(timeout=2)


def test_startup_uses_a_healthy_saved_connection(recovery):
    controller, backend, store, clock = recovery
    backend.upstream.return_value = {"address": "192.168.1.90", "ssid": "winter"}
    controller.start()
    assert controller.snapshot.state == "online"
    assert controller.snapshot.address == "192.168.1.90"
    backend.upstream.assert_called_once_with(timeout=2)
    backend.ensure_access_point.assert_not_called()
    assert store.data["waiting"] is False


def test_saved_connection_gets_a_short_window_before_wifi_chooser(recovery):
    _, backend, store, clock = recovery
    saved = {"ssid": "home", "psk": "a" * 64}
    store.data["saved_network"] = saved
    controller = NetworkController(backend, store, clock=lambda: clock[0],
                                   saved_connection_seconds=15)
    controller.start()
    assert controller.snapshot.state == "starting"
    backend.activate_saved.assert_called_once_with(saved)
    assert backend.upstream.call_count == 1
    assert "DigitalFrame-" not in controller.snapshot.banner()
    clock[0] += 6
    controller.step()
    assert controller.snapshot.state == "starting"
    clock[0] += 9
    controller.step()
    assert controller.snapshot.state == "ap"
    assert controller.snapshot.can_submit
    assert store.data["waiting"] is True
    assert backend.ensure_access_point.call_count == 1
    backend.reset_mock()
    clock[0] += 3600
    controller.step()
    backend.upstream.assert_not_called()


def test_saved_connection_can_succeed_during_startup_window(recovery):
    _, backend, store, clock = recovery
    controller = NetworkController(backend, store, clock=lambda: clock[0],
                                   saved_connection_seconds=15)
    controller.start()
    backend.upstream.return_value = {"address": "192.168.1.90", "ssid": "winter"}
    clock[0] += 4
    controller.step()
    assert controller.snapshot.online
    assert store.data["waiting"] is False
    backend.ensure_access_point.assert_not_called()


def test_startup_offers_last_successful_control_panel_network(recovery):
    _, backend, store, clock = recovery
    saved = {"ssid": "home", "psk": "a" * 64}
    store.data["saved_network"] = saved
    store.save()
    controller = NetworkController(backend, StateFile(store.path), clock=lambda: clock[0],
                                   saved_connection_seconds=15)
    controller.start()
    backend.activate_saved.assert_called_once_with(saved)
    assert controller.snapshot.state == "starting"
    backend.upstream.return_value = {"address": "192.168.1.90", "ssid": "home"}
    clock[0] += 6
    controller.step()
    assert controller.snapshot.online
    backend.ensure_access_point.assert_not_called()


def test_saved_connection_probe_errors_still_fall_back_to_wifi_chooser(recovery):
    _, backend, store, clock = recovery
    controller = NetworkController(backend, store, clock=lambda: clock[0],
                                   saved_connection_seconds=15)
    backend.upstream.side_effect = OSError("supplicant not ready")
    controller.start()
    assert controller.snapshot.state == "starting"
    clock[0] += 15
    controller.step()
    assert controller.snapshot.can_submit
    assert store.data["waiting"] is True


def test_stop_during_saved_connection_window_returns_without_starting_hotspot(recovery):
    _, backend, store, clock = recovery
    controller = NetworkController(backend, store, clock=lambda: clock[0],
                                   saved_connection_seconds=15)
    controller.start()
    controller.stop()
    clock[0] += 20
    controller.step()
    backend.ensure_access_point.assert_not_called()


def test_worker_stop_wakes_saved_connection_wait(recovery):
    _, backend, store, _ = recovery
    probed = Event()
    backend.upstream.side_effect = lambda **kwargs: (probed.set(), None)[1]
    controller = NetworkController(backend, store, saved_connection_seconds=15)
    worker = Thread(target=controller.run)
    worker.start()
    try:
        assert probed.wait(2)
        controller.stop()
        worker.join(2)
        assert not worker.is_alive()
        backend.ensure_access_point.assert_not_called()
    finally:
        controller.stop()
        worker.join(2)


def test_selected_online_connection_enters_ap_after_outage(recovery):
    controller, backend, store, clock = recovery
    controller.start()
    controller.publish(state="online", address="192.168.1.90", ssid="winter")
    store.data["waiting"] = False
    backend.upstream.return_value = {"address": "192.168.1.90", "ssid": "winter"}
    backend.reset_mock()
    controller.event()  # A link/address event or suspected cloud failure.
    controller.step()
    assert controller.snapshot.online
    backend.upstream.return_value = None
    clock[0] += 31
    controller.step()
    assert controller.snapshot.state == "ap"
    assert store.data["waiting"]


@pytest.mark.parametrize("success", [False, True])
def test_one_submission_waits_for_response_then_commits_or_restores_hotspot(recovery, success):
    controller, backend, store, clock = recovery
    controller.start()
    before = controller.snapshot
    backend.reset_mock()
    operation = controller.reserve(" home network ", "02:00:00:00:00:01", " password ")
    assert controller.snapshot.state == "connecting"
    with pytest.raises(NetworkError):
        controller.reserve("another", "02:00:00:00:00:02", "password")
    controller.step()
    backend.connect.assert_not_called()
    controller.commit(operation)
    controller.commit(operation)  # Idempotent delivery does not restart its deadline.
    clock[0] += 1
    controller.step()
    backend.connect.assert_not_called()
    if success:
        backend.connect.return_value = {"address": "192.168.1.90", "ssid": " home network "}
    else:
        # An empty fresh scan must not leave the boot-time list on the panel.
        backend.scan_access_points.return_value = ()
    clock[0] += 5
    controller.step()
    backend.connect.assert_called_once_with(
        " home network ", "02:00:00:00:00:01", " password ", store)
    assert controller.snapshot.online is success
    assert store.data["waiting"] is not success
    if not success:
        assert controller.snapshot.can_refresh
        assert not controller.snapshot.can_submit
        assert controller.snapshot.ap_password == before.ap_password
        assert controller.snapshot.address == before.address
        assert controller.snapshot.access_points == ()
        backend.restore.assert_not_called()
        backend.scan_access_points.assert_called_once()
    clock[0] += 100000
    if not success:
        backend.reset_mock()
        controller.step()
        backend.connect.assert_not_called()
        backend.upstream.assert_not_called()


def test_timed_out_connection_attempt_returns_to_wifi_chooser(recovery):
    controller, backend, store, clock = recovery
    controller.start()
    backend.connect.side_effect = TimeoutError("bounded connection attempt expired")
    backend.reset_mock()

    operation = controller.reserve("home", "02:00:00:00:00:01", "password")
    controller.commit(operation)
    clock[0] += 6
    controller.step()

    backend.connect.assert_called_once_with(
        "home", "02:00:00:00:00:01", "password", store)
    backend.restore.assert_not_called()
    backend.scan_access_points.assert_called_once()
    backend.ensure_access_point.assert_called_once()
    assert controller.snapshot.state == "ap"
    assert controller.snapshot.can_submit
    assert controller.snapshot.message == (
        "Connection attempt failed. Enter your Wi-Fi details to try again.")


def test_failed_connection_refreshes_access_points_before_next_page_load(recovery):
    controller, backend, store, clock = recovery
    controller.start()
    refreshed = (
        {"ssid": "new home", "bssid": "02:00:00:00:00:03", "signal": -35,
         "channel": 1, "security": "WPA2", "supported": True},
    )
    backend.reset_mock()
    backend.scan_access_points.return_value = refreshed

    operation = controller.reserve("home", "02:00:00:00:00:01", "password")
    controller.commit(operation)
    clock[0] += 6
    controller.step()

    backend.restore.assert_not_called()
    assert backend.mock_calls.index(call.scan_access_points()) < backend.mock_calls.index(
        call.ensure_access_point(store))
    assert controller.snapshot.access_points == refreshed
    page = render_page(5, wifi=controller.snapshot).body.decode()
    assert "new home — 02:00:00:00:00:03" in page
    assert "home — 02:00:00:00:00:01" not in page


def test_uncommitted_request_expires_without_dropping_ap(recovery):
    controller, backend, _, clock = recovery
    controller.start()
    backend.reset_mock()
    operation = controller.reserve("home", "02:00:00:00:00:01", "password")
    clock[0] += 16
    controller.step()
    assert controller.snapshot.can_submit
    backend.connect.assert_not_called()
    backend.ensure_access_point.assert_not_called()
    with pytest.raises(NetworkError):
        controller.commit(operation)


def test_refresh_temporarily_restores_station_scan_then_restarts_ap(recovery):
    controller, backend, _, clock = recovery
    controller.start()
    backend.reset_mock()
    refreshed = (
        {"ssid": "other", "bssid": "02:00:00:00:00:03", "signal": -35,
         "channel": 1, "security": "WPA2", "supported": True},
    )
    backend.scan_access_points.return_value = refreshed
    backend.ensure_access_point.return_value = "10.42.0.1"
    operation = controller.reserve_refresh()
    assert controller.snapshot.state == "refreshing"
    controller.commit(operation)
    clock[0] += 6
    controller.step()
    backend.restore.assert_called_once()
    backend.scan_access_points.assert_called_once()
    backend.ensure_access_point.assert_called_once()
    assert controller.snapshot.state == "ap"
    assert controller.snapshot.access_points == refreshed


def test_client_connect_reserves_and_commits_in_one_helper_request(recovery, tmp_path, allow_local_socket):
    controller, _, _, _ = recovery
    controller.start()
    server = Server(str(tmp_path / "network.sock"), Handler)
    server.allowed_uid = os.getuid()
    server.controller = controller
    serving = Thread(target=server.serve_forever)
    serving.start()
    try:
        NetworkClient(tmp_path / "network.sock").connect(
            "home", "02:00:00:00:00:01", "test-secret")
        assert controller.pending["kind"] == "connect"
        assert controller.pending["ready"] is not None
    finally:
        server.shutdown()
        server.server_close()
        serving.join()


def test_failed_boot_activation_falls_back_to_ap(recovery):
    controller, backend, store, _ = recovery
    store.data["saved_uuid"] = "saved"
    backend.activate_saved.side_effect = TimeoutError()
    controller.start()
    assert controller.snapshot.can_submit
    backend.activate_saved.assert_called_once_with(None)


def test_corrupt_recovery_record_does_not_attempt_upstream(tmp_path):
    path = tmp_path / "state.json"
    path.write_text("broken")
    store = StateFile(path)
    assert store.data["waiting"] and store.damaged
    backend = Mock()
    backend.ensure_access_point.return_value = "10.42.0.1"
    backend.scan_access_points.return_value = ()
    controller = NetworkController(backend, store)
    controller.start()
    assert controller.snapshot.state == "ap"
    backend.upstream.assert_not_called()


def test_failed_ap_does_not_loop_on_its_own_disconnect_events(recovery):
    controller, backend, _, clock = recovery
    backend.ensure_access_point.side_effect = OSError("Driver rejected AP")
    controller.start()
    assert controller.snapshot.state == "unavailable"
    backend.reset_mock()
    for _ in range(3):
        clock[0] += 10000
        controller.event()
        controller.step()
    backend.ensure_access_point.assert_not_called()
    backend.upstream.assert_not_called()
    controller.event(recover=True)  # Adapter or helper became available again.
    controller.step()
    backend.ensure_access_point.assert_called_once()


@pytest.mark.parametrize("ssid,password", [("", "password"), ("界" * 11, "password"), ("\ud800", "password"),
    ("home\n", "password"), ("home", "short"), ("home", "x" * 64), ("home", "abc\n1234")])
def test_invalid_credentials_do_not_echo_secrets(ssid, password):
    with pytest.raises(NetworkError) as error:
        validate_credentials(ssid, password)
    assert password not in str(error.value)


def test_subnet_selection_checks_routes_and_known_previous_networks():
    assert select_subnet(["0.0.0.0/0", "192.168.1.0/24"]) == "10.42.0.1"
    assert select_subnet(["10.42.0.0/23", "10.42.2.5/32"]) == "10.42.3.1"
    assert select_subnet([], "10.42.5.1") == "10.42.5.1"
    assert select_subnet(["10.0.0.0/8"]) == "172.30.240.1"
    with pytest.raises(NetworkError):
        select_subnet(["10.0.0.0/8", "172.16.0.0/12", "192.168.0.0/16"])


def test_regulatory_country_applies_to_hotspot_and_home_station(tmp_path, monkeypatch):
    backend = Networkd("wlan0", "02:00:00:00:00:01", "cn", runtime=tmp_path,
                       network_file=tmp_path / "network.conf")
    store = StateFile(tmp_path / "state.json")
    store.data.update(ap_ssid="DigitalFrame-TEST", ap_password="jamesbond")
    monkeypatch.setattr(backend, "_routes", lambda: [])
    monkeypatch.setattr(backend, "_take_link", lambda network: None)
    configs = []

    def start(config, mode):
        configs.append((config, mode))
        backend.process = Mock(poll=Mock(return_value=None))
        backend.mode = mode

    monkeypatch.setattr(backend, "_start_supplicant", start)
    monkeypatch.setattr(backend, "_status", lambda **kwargs: {"mode": "AP"})
    assert backend.ensure_access_point(store) == "10.42.0.1"
    assert "country=CN\n" in configs[0][0] and configs[0][1] == "ap"

    monkeypatch.setattr(backend, "_status", lambda **kwargs: {
        "mode": "station", "wpa_state": "COMPLETED", "ssid": "home"})
    monkeypatch.setattr(backend, "_run", lambda *args, **kwargs: Mock())
    monkeypatch.setattr(backend, "_address_info", lambda status, **kwargs: {
        "address": "192.168.1.23", "ssid": status["ssid"], "interface": "wlan0"})
    assert backend.connect("home", "02:00:00:00:00:02", "secret-password", store)["address"] == "192.168.1.23"
    assert "country=CN\n" in configs[1][0] and configs[1][1] == "station"
    assert store.data["saved_network"] == {
        "ssid": "home", "psk": networkd._psk("home", "secret-password")}
    assert "secret-password" not in store.path.read_text()
    assert store.path.stat().st_mode & 0o777 == 0o600
    assert backend.upstream()["ssid"] == "home"  # No third-party HTTP probe.
    with pytest.raises(NetworkError, match="two-letter"):
        Networkd("wlan0", "02:00:00:00:00:01", "China")


def test_saved_panel_network_is_added_to_os_supplicant(tmp_path):
    backend = Networkd("wlan0", "02:00:00:00:00:01", "US", runtime=tmp_path,
                       network_file=tmp_path / "network.conf")
    backend._run = Mock()
    backend._control = Mock(side_effect=lambda command, **_: "2" if command == "ADD_NETWORK" else "OK")
    saved = {"ssid": "new home", "psk": "A" * 64}

    assert backend.activate_saved(saved)
    backend._run.assert_called_once_with(
        [networkd.SYSTEMCTL, "start", backend.netplan_service], timeout=5, check=False)
    assert call("ADD_NETWORK", helper=False, timeout=1) in backend._control.mock_calls
    assert call("SET_NETWORK 2 ssid 6e657720686f6d65", helper=False, timeout=1) in backend._control.mock_calls
    assert call("SET_NETWORK 2 psk " + "a" * 64, helper=False, timeout=1) in backend._control.mock_calls
    assert call("ENABLE_NETWORK 2", helper=False, timeout=1) in backend._control.mock_calls
    assert call("RECONNECT", helper=False, timeout=1) in backend._control.mock_calls
    assert call("REMOVE_NETWORK 2", helper=False, timeout=1) not in backend._control.mock_calls
    backend._control.reset_mock()
    assert not backend.activate_saved({"ssid": "home", "psk": "bad"})
    backend._control.assert_called_once_with("RECONNECT", helper=False, timeout=1)


def test_failed_saved_profile_setup_leaves_os_profiles_available(tmp_path):
    backend = Networkd("wlan0", "02:00:00:00:00:01", "US", runtime=tmp_path,
                       network_file=tmp_path / "network.conf")
    backend._run = Mock()
    backend._control = Mock(side_effect=lambda command, **_: (
        "3" if command == "ADD_NETWORK" else
        "FAIL" if command.startswith("SET_NETWORK 3 psk ") else "OK"))

    assert not backend.activate_saved({"ssid": "home", "psk": "a" * 64})
    assert call("REMOVE_NETWORK 3", helper=False, timeout=1) in backend._control.mock_calls
    assert backend._control.mock_calls[-1] == call("RECONNECT", helper=False, timeout=1)


def test_scan_keeps_mesh_satellites_as_individual_access_points():
    output = """bssid / frequency / signal level / flags / ssid
3a:98:b5:98:fb:dd\t2452\t-58\t[WPA2-PSK-CCMP][ESS]\twinter
3a:98:b5:9a:89:98\t2452\t-90\t[WPA2-PSK-CCMP][ESS]\twinter
00:11:22:33:44:55\t5180\t-50\t[SAE][ESS]\tnewer
00:11:22:33:44:66\t2412\t-40\t[WPA2-PSK-CCMP][ESS]\t
"""
    points = parse_scan_results(output)
    assert [point["bssid"] for point in points if point["ssid"] == "winter"] == [
        "3a:98:b5:98:fb:dd", "3a:98:b5:9a:89:98"]
    newer = next(point for point in points if point["ssid"] == "newer")
    assert not newer["supported"]
    assert next(point for point in points if point["ssid"] == "winter")["channel"] == 9
    hidden = next(point for point in points if point["bssid"] == "00:11:22:33:44:66")
    assert hidden["ssid"] == "Hidden network" and not hidden["supported"]


def test_failed_station_scans_with_its_own_supplicant_without_netplan_handoff(tmp_path, monkeypatch):
    backend = Networkd("wlan0", "02:00:00:00:00:01", "US", runtime=tmp_path,
                       network_file=tmp_path / "network.conf")
    backend.owns_link = True
    backend.mode = "station"
    backend.process = Mock(poll=Mock(return_value=None))
    output = ("bssid / frequency / signal level / flags / ssid\n"
              "02:00:00:00:00:03\t2412\t-35\t[WPA2-PSK-CCMP][ESS]\tnew home\n")
    attempts = ["FAIL-BUSY", "OK"]

    def control(command, *, helper):
        assert helper is True
        if command == "SCAN":
            return attempts.pop(0)
        return output if command == "SCAN_RESULTS" else "OK"

    backend._control = Mock(side_effect=control)
    monkeypatch.setattr(networkd.time, "sleep", lambda _: None)
    points = backend.scan_access_points()

    assert [point["ssid"] for point in points] == ["new home"]
    assert backend._control.mock_calls.index(call("DISCONNECT", helper=True)) < (
        backend._control.mock_calls.index(call("SCAN", helper=True)))
    assert backend._control.call_count >= 4
    backend.mode = "ap"
    backend._control.reset_mock()
    assert backend.scan_access_points() == ()
    backend._control.assert_not_called()


def test_wifi_html_sections_validation_disabled_states_and_credential_handoff(recovery):
    controller, backend, _, _ = recovery
    controller.start()
    network = Mock()
    network.snapshot.side_effect = lambda: controller.snapshot
    network.connect.side_effect = lambda ssid, bssid, password: controller.commit(
        controller.reserve(ssid, bssid, password))
    settings = RuntimeSettings(5, folders=lambda: ["kids"])
    with TestClient(create_app(settings, network=network)) as browser:
        page = browser.get("/").text
        assert (page.index("<h2>Slideshow control") <
                page.index("<h2>Wi-Fi control") <
                page.index("<h2>Logs and comments"))
        assert 'id="wifi-password" name="password" type="text"' in page
        assert '<button type="submit">Apply Wi-Fi</button>' in page
        assert '<button type="submit">Refresh access points</button>' in page
        assert controller.snapshot.ap_password not in page
        token = re.search(r'name="token" value="([^"]+)"', page)[1]
        assert page.count("home — 02:00:00:00:00:") == 2
        payload = {"bssid": "02:00:00:00:00:01", "password": "test-secret", "token": token}
        assert browser.post("/wifi", data={**payload, "token": "bad"}).status_code == 403
        assert browser.post("/wifi", data=payload, headers={"origin": "https://evil.invalid"}).status_code == 403
        assert browser.post("/wifi", data={**payload, "password": "short"}).status_code == 422
        network.connect.assert_not_called()
        response = browser.post("/wifi", data=payload, follow_redirects=False)
        assert response.status_code == 303
        assert response.headers["location"] == "/"
        assert payload["password"] not in response.text
        network.connect.assert_called_once_with("home", "02:00:00:00:00:01", "test-secret")
        backend.connect.assert_not_called()
        assert browser.post("/wifi", data=payload).status_code == 409
        assert browser.post("/settings", data={"display_seconds": "8"}).status_code == 200
        assert browser.post("/folder", data={"folder": "kids"}).status_code == 200
        assert settings.display_seconds == 8 and settings.selected_folder == "kids"
        controller.publish(state="online", ssid='<home & "wifi">')
        page = browser.get("/").text
        assert '<button type="submit" disabled>Apply Wi-Fi</button>' in page
        assert '&lt;home &amp; &quot;wifi&quot;&gt;' in page
        assert browser.post("/wifi", data=payload).status_code == 409


def test_wifi_refresh_route_uses_one_atomic_helper_request(recovery):
    controller, _, _, _ = recovery
    controller.start()
    network = Mock()
    network.snapshot.side_effect = lambda: controller.snapshot
    with TestClient(create_app(RuntimeSettings(5), network=network)) as browser:
        token = re.search(r'name="token" value="([^"]+)"', browser.get("/").text)[1]
        response = browser.post(
            "/wifi/refresh", data={"token": token}, follow_redirects=False,
        )
        assert response.status_code == 303
        assert response.headers["location"] == "/"
        network.refresh.assert_called_once_with()


def test_wifi_route_never_logs_backend_exception_secrets(recovery, caplog):
    controller, _, _, _ = recovery
    controller.start()
    network = Mock()
    network.snapshot.return_value = controller.snapshot
    network.connect.side_effect = RuntimeError("private-password")
    with TestClient(create_app(RuntimeSettings(5), network=network)) as browser:
        token = re.search(r'name="token" value="([^"]+)"', browser.get("/").text)[1]
        response = browser.post("/wifi", data={"bssid": "02:00:00:00:00:01",
                                                "password": "private-password", "token": token})
        assert response.status_code == 503
        assert "private-password" not in response.text + caplog.text


def test_sync_waits_offline_and_cancels_pass_even_after_fast_reconnect(app, monkeypatch):
    from client.main import NetworkCancellation, SyncWorker
    from client.status import RuntimeStatus
    network = NetworkClient("/unused")
    stop = Event()
    network._publish(NetworkSnapshot(state="online"))
    token = NetworkCancellation(stop, network)
    network._publish(NetworkSnapshot(state="ap"))
    assert token.is_set()
    called = Event()
    sync = Mock(side_effect=lambda *args, **kwargs: (called.set(), Mock(network_error=False))[1])
    monkeypatch.setattr(app.sync, "sync_photos", sync)
    worker = SyncWorker(Mock(), RuntimeStatus(), Mock(), 3600, network=network)
    worker.start()
    assert not called.wait(.05)
    network._publish(NetworkSnapshot(state="online"))
    assert token.is_set()  # A cancelled pass cannot restart itself after recovery.
    assert called.wait(2)
    worker.stop()
    assert not worker.thread.is_alive()
    assert sync.call_count == 1


def test_network_url_uses_ap_interface_and_actual_listener_port():
    from client.control.server import ControlSupervisor
    network = NetworkClient("/unused")
    server = ControlSupervisor(Mock(), "0.0.0.0", 0, Mock(), network=network)
    network._publish(NetworkSnapshot(state="ap", address="10.42.2.1"))
    assert server.url is None
    server.bound_port = 34567
    assert server.url == "http://10.42.2.1:34567"
    network._publish(NetworkSnapshot(state="connecting", address="10.42.2.1"))
    assert server.url is None
    network._publish(NetworkSnapshot(state="online", address="192.168.1.90"))
    assert server.url == "http://192.168.1.90:34567"


def test_hotspot_banner_is_unlimited_through_changes_attempts_and_recovery(app, monkeypatch):
    from client.overlay import SlideshowOverlay
    player = app.FakeMPV()
    clock = [0]
    monkeypatch.setattr("client.overlay.time.monotonic", lambda: clock[0])
    state = NetworkSnapshot(state="ap", ap_ssid="DigitalFrame-TEST", ap_password="setup-password",
                            ap_address="10.42.0.1", message="Wi-Fi unavailable — cached slideshow continues.")
    banner = SlideshowOverlay(player, None, 0)
    banner.set_network_message(state.banner("http://10.42.0.1:8000"))
    for _ in range(3):
        clock[0] += 36000
        banner.new_frame()
        banner.show_message("Photo folder: kids", 15)
        banner.update()
        assert banner.deadline is None
        assert "setup-password" in banner._network_text
        assert "10.42.0.1:8000" in player.overlays[1][0]
        assert player.overlays[1][1] == "red"
    banner.set_network_message(replace(state, state="connecting").banner())
    assert "setup-password" in player.overlays[1][0]
    assert "10.42.0.1:8000" in player.overlays[1][0]
    clock[0] += 60
    banner.new_frame()
    banner.set_network_message(replace(state, state="online").banner())
    assert 1 not in player.overlays


def test_online_wifi_still_displays_a_cloud_sync_failure(app):
    app.FakeMPV.wait_hook = lambda player, _: setattr(player, "running", False)
    status = Mock()
    status.network_problem.return_value = True
    network = Mock(control_port=8000)
    network.snapshot.return_value = NetworkSnapshot(state="online", address="192.168.1.23")
    app.slideshow.show_slideshow(RuntimeSettings(1), network=network, status=status)
    assert "Cloud connection problem" in app.FakeMPV.instances[-1].overlays[1][0]
