"""Restricted root helper entry point, installed separately from the user's checkout."""

from dataclasses import asdict
import json
import logging
import os
from pathlib import Path
import pwd
import re
import signal
import socket
import socketserver
import struct
from threading import BoundedSemaphore, Thread

from .controller import NetworkController, StateFile
from .network_manager import NetworkManager, NM, DEVICE, PROPS
from .state import NetworkError


class Handler(socketserver.StreamRequestHandler):
    def handle(self):
        self.request.settimeout(5)
        _, uid, _ = struct.unpack("3i", self.request.getsockopt(socket.SOL_SOCKET, socket.SO_PEERCRED, 12))
        if uid not in {0, self.server.allowed_uid}:
            return
        controller = self.server.controller
        try:
            line = self.rfile.readline(4097)
            if len(line) > 4096:
                return
            request = json.loads(line)
            operation = request.get("op")
            if operation == "watch":
                revision = -1
                while not controller.stopped:
                    with controller.condition:
                        controller.condition.wait_for(
                            lambda: controller.snapshot.revision != revision or controller.stopped, timeout=25)
                        snapshot = controller.snapshot
                    self.wfile.write((json.dumps(asdict(snapshot)) + "\n").encode())
                    self.wfile.flush()
                    revision = snapshot.revision
                return
            if operation == "reserve":
                identity = controller.reserve(request.get("ssid"), request.get("password"))
                result = {"ok": True, "operation": identity}
            elif operation == "commit" and isinstance(request.get("operation"), str):
                controller.commit(request["operation"])
                result = {"ok": True}
            elif operation == "check":
                if controller.snapshot.online:
                    controller.event()
                result = {"ok": True}
            else:
                raise NetworkError("Unsupported Wi-Fi request.")
        except NetworkError as exc:
            result = {"ok": False, "error": str(exc)}
        except Exception:
            result = {"ok": False, "error": "Unable to process the Wi-Fi request."}
        try:
            self.wfile.write((json.dumps(result) + "\n").encode())
        except OSError:
            pass


class Server(socketserver.ThreadingMixIn, socketserver.UnixStreamServer):
    daemon_threads = True

    def __init__(self, *args, **kwargs):
        self.slots = BoundedSemaphore(16)
        super().__init__(*args, **kwargs)

    def process_request(self, request, client_address):
        if not self.slots.acquire(blocking=False):
            self.shutdown_request(request)
            return
        try:
            super().process_request(request, client_address)
        except Exception:
            self.slots.release()
            raise

    def process_request_thread(self, request, client_address):
        try:
            super().process_request_thread(request, client_address)
        finally:
            self.slots.release()

    def handle_error(self, request, client_address):
        # Never include a credential-bearing request/traceback in service logs.
        pass


def main():
    import dbus
    from dbus.mainloop.glib import DBusGMainLoop
    from gi.repository import GLib

    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(message)s")

    if os.geteuid() != 0:
        raise SystemExit("Install and start the system network helper as root.")
    config = json.loads(Path("/etc/digitalframe-network.json").read_text())
    interface, mac = config["interface"], config["mac"]
    if not re.fullmatch(r"[a-zA-Z0-9_.-]{1,15}", interface) or not re.fullmatch(r"(?:[0-9a-fA-F]{2}:){5}[0-9a-fA-F]{2}", mac):
        raise SystemExit("Invalid board interface configuration.")
    user = pwd.getpwnam(config["user"])
    os.umask(0o077)
    DBusGMainLoop(set_as_default=True)
    controller = NetworkController(NetworkManager(interface, mac), StateFile("/var/lib/digitalframe-network/state.json"))
    bus = dbus.SystemBus(private=True)
    # Listen only to link/address lifecycle events, not Wi-Fi scan or signal-strength chatter.
    bus.add_signal_receiver(lambda *args: controller.event(), signal_name="StateChanged", dbus_interface=DEVICE)
    def properties(interface_name, values, invalidated):
        if interface_name == NM and {"PrimaryConnection", "ActiveConnections"}.intersection(values):
            controller.event()
        elif interface_name == DEVICE and {"Ip4Config", "Interface"}.intersection(values):
            controller.event()
    bus.add_signal_receiver(properties, signal_name="PropertiesChanged", dbus_interface=PROPS, bus_name=NM)
    bus.add_signal_receiver(lambda name, old, new: controller.event(recover=bool(new)), signal_name="NameOwnerChanged",
                            dbus_interface="org.freedesktop.DBus", arg0=NM)
    bus.add_signal_receiver(lambda *args: controller.event(recover=True), signal_name="DeviceAdded", dbus_interface=NM)
    directory = Path("/run/digitalframe-network")
    directory.mkdir(mode=0o750, exist_ok=True)
    os.chown(directory, 0, user.pw_gid)
    os.chmod(directory, 0o750)
    path = directory / "control.sock"
    path.unlink(missing_ok=True)
    server = Server(str(path), Handler)
    server.allowed_uid, server.controller = user.pw_uid, controller
    os.chown(path, 0, user.pw_gid)
    os.chmod(path, 0o660)
    def run_controller():
        try:
            controller.run()
        except BaseException:
            # Let systemd recover a dead worker without logging secret-bearing
            # driver exceptions or leaving a healthy-looking but inert helper.
            os._exit(1)
    worker = Thread(target=run_controller, name="network-operations", daemon=True)
    worker.start()
    serving = Thread(target=server.serve_forever, name="network-socket", daemon=True)
    serving.start()
    loop = GLib.MainLoop()
    def stop(*args):
        controller.stop()
        loop.quit()
    signal.signal(signal.SIGTERM, stop)
    signal.signal(signal.SIGINT, stop)
    try:
        loop.run()
    finally:
        controller.stop()
        server.shutdown()
        server.server_close()
        path.unlink(missing_ok=True)


if __name__ == "__main__":
    main()
