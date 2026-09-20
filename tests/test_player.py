"""Exercise the real JSON IPC transport without requiring a display or mpv."""

import json
import time

import pytest

from client.display import (
    DRMMode, choose_mode, parse_drm_modes, preferred_drm_options,
)
from client.player import MPVError, MPVPlayer, _ass_text, _background_commands


FAKE_MPV = r'''#!/usr/bin/env python3
import json
import os
import socket
import sys
import time

with open(os.environ["FAKE_MPV_ARGS"], "w", encoding="utf-8") as output:
    json.dump(sys.argv[1:], output)
argument = next(value for value in sys.argv if value.startswith("--input-ipc-client=fd://"))
fd = int(argument.rsplit("/", 1)[1])
connection = socket.socket(fileno=fd)
reader = connection.makefile("r", encoding="utf-8")
entry = 0
for line in reader:
    request = json.loads(line)
    command = request["command"]
    name = command.get("name") if isinstance(command, dict) else command[0]
    if name == "get_property":
        delay = float(os.environ.get("FAKE_MPV_STARTUP_DELAY", "0"))
        if delay:
            time.sleep(delay)
        if os.environ.get("FAKE_MPV_DROP_STARTUP_REPLY"):
            print("simulated DRM startup failure", file=sys.stderr, flush=True)
            continue
    if isinstance(command, dict) and "_name" in command:
        connection.sendall((json.dumps({"request_id": request["request_id"], "error": "invalid parameter"}) + "\n").encode())
        continue
    properties = {
        "mpv-version": "mpv 0.37.0",
        "current-vo": "gpu",
        "display-fps": 30.0,
        "osd-dimensions": {"w": 1920, "h": 1080},
    }
    data = properties.get(command[1]) if name == "get_property" else None
    connection.sendall((json.dumps({"request_id": request["request_id"], "error": "success", "data": data}) + "\n").encode())
    if name == "loadfile":
        entry += 1
        connection.sendall((json.dumps({"event": "start-file", "playlist_entry_id": entry}) + "\n").encode())
        if "bad" in command[1]:
            event = {"event": "end-file", "reason": "error", "playlist_entry_id": entry, "file_error": "broken image"}
            connection.sendall((json.dumps(event) + "\n").encode())
        else:
            connection.sendall(b'{"event":"file-loaded"}\n')
            if "slow" in command[1]:
                time.sleep(0.15)
            connection.sendall(b'{"event":"playback-restart"}\n')
    if name == "quit":
        connection.sendall(b'{"event":"shutdown"}\n')
        break
'''


@pytest.fixture
def fake_mpv(tmp_path):
    executable = tmp_path / "mpv"
    executable.write_text(FAKE_MPV)
    executable.chmod(0o755)
    return executable


def test_player_uses_fullscreen_low_overhead_ipc_and_waits_for_decode(
    fake_mpv, tmp_path, allow_local_socket, monkeypatch,
):
    arguments_file = tmp_path / "arguments.json"
    monkeypatch.setenv("FAKE_MPV_ARGS", str(arguments_file))
    try:
        player = MPVPlayer(str(fake_mpv), command_timeout=2, load_timeout=2)
    except MPVError as exc:
        if isinstance(exc.__cause__, PermissionError):
            pytest.skip("sandbox blocks inherited Unix socket IPC")
        raise
    try:
        assert player.running
        player.load(tmp_path / "good photo.jpg")
        player.set_overlay(1, "Control: {frame}\\name\nsecond line", color="red")
        player.clear_overlay(1)
        with pytest.raises(MPVError, match="broken image"):
            player.load(tmp_path / "bad.jpg")
    finally:
        player.close()
    assert not player.running
    arguments = json.loads(arguments_file.read_text())
    assert {
        "--no-config", "--fullscreen=yes", "--keepaspect=yes", "--panscan=0",
        "--image-display-duration=inf", "--audio=no",
    } <= set(arguments)
    assert not any(argument.startswith("--background") for argument in arguments)


def test_player_applies_an_edid_selected_drm_mode(
    fake_mpv, tmp_path, allow_local_socket, monkeypatch,
):
    arguments_file = tmp_path / "arguments.json"
    monkeypatch.setenv("FAKE_MPV_ARGS", str(arguments_file))
    try:
        player = MPVPlayer(
            str(fake_mpv), command_timeout=2, load_timeout=2,
            drm_options=("--vo=gpu", "--gpu-context=drm", "--drm-mode=7"),
        )
    except MPVError as exc:
        if isinstance(exc.__cause__, PermissionError):
            pytest.skip("sandbox blocks inherited Unix socket IPC")
        raise
    player.close()

    arguments = json.loads(arguments_file.read_text())
    assert "--vo=gpu" in arguments
    assert "--gpu-context=drm" in arguments
    assert "--drm-mode=7" in arguments


def test_drm_mode_parser_and_selector_prefer_largest_progressive_30hz_mode():
    output = """
    [vo/gpu/drm]   Mode 0: 3840x2160 (3840x2160@30.00Hz)
    [vo/gpu/drm]   Mode 1: 1920x1080 (1920x1080@60.00Hz)
    [vo/gpu/drm]   Mode 2: 1920x1080 (1920x1080@29.97Hz)
    [vo/gpu/drm]   Mode 3: 1920x1080i (1920x1080@30.00Hz)
    [vo/gpu/drm]   Mode 4: 1280x720 (1280x720@30.00Hz)
    """
    modes = parse_drm_modes(output)

    assert modes[0] == DRMMode(0, "3840x2160", 3840, 2160, 30.0)
    assert choose_mode(
        modes, preferred_hz=30, max_width=1920, max_height=1080,
    ) == modes[2]


def test_drm_mode_selector_preserves_automatic_mode_without_a_30hz_match():
    modes = parse_drm_modes(
        "Mode 0: 1920x1080 (1920x1080@60.00Hz)\n"
        "Mode 1: 1280x720 (1280x720@50.00Hz)\n"
    )

    assert choose_mode(
        modes, preferred_hz=30, max_width=1920, max_height=1080,
    ) is None


def test_drm_probe_uses_the_connected_displays_exact_mode_index(monkeypatch):
    output = """
    [vo/gpu/drm] Available modes:
    [vo/gpu/drm]   Mode 5: 1920x1080 (1920x1080@60.00Hz)
    [vo/gpu/drm]   Mode 6: 1920x1080 (1920x1080@29.97Hz)
    """
    result = type("Result", (), {"stdout": output})()
    monkeypatch.setattr("client.display._direct_drm_available", lambda: True)
    monkeypatch.setattr("client.display.subprocess.run", lambda *args, **kwargs: result)

    options = preferred_drm_options(
        "mpv", preferred_hz=30, max_width=1920, max_height=1080,
    )

    assert options == ("--vo=gpu", "--gpu-context=drm", "--drm-mode=6")


def test_ass_overlay_text_is_escaped():
    assert _ass_text("{a}\\b\nc") == r"\{a\}\\b\Nc"


def test_load_waits_until_mpv_presents_the_first_frame(
    fake_mpv, tmp_path, allow_local_socket, monkeypatch,
):
    monkeypatch.setenv("FAKE_MPV_ARGS", str(tmp_path / "arguments.json"))
    try:
        player = MPVPlayer(str(fake_mpv), command_timeout=2, load_timeout=2)
    except MPVError as exc:
        if isinstance(exc.__cause__, PermissionError):
            pytest.skip("sandbox blocks inherited Unix socket IPC")
        raise
    try:
        started = time.monotonic()
        player.load(tmp_path / "slow.jpg")
        elapsed = time.monotonic() - started
    finally:
        player.close()

    assert elapsed >= 0.12


def test_initial_handshake_has_a_separate_longer_timeout(
    fake_mpv, tmp_path, allow_local_socket, monkeypatch,
):
    monkeypatch.setenv("FAKE_MPV_ARGS", str(tmp_path / "arguments.json"))
    monkeypatch.setenv("FAKE_MPV_STARTUP_DELAY", "0.1")

    player = MPVPlayer(
        str(fake_mpv), startup_timeout=0.5, command_timeout=0.02,
        load_timeout=2,
    )
    player.close()


def test_failed_startup_logs_bounded_mpv_stderr(
    fake_mpv, tmp_path, allow_local_socket, monkeypatch, caplog,
):
    monkeypatch.setenv("FAKE_MPV_ARGS", str(tmp_path / "arguments.json"))
    monkeypatch.setenv("FAKE_MPV_DROP_STARTUP_REPLY", "1")

    with pytest.raises(MPVError, match="did not answer"):
        MPVPlayer(
            str(fake_mpv), startup_timeout=0.05, command_timeout=0.05,
            load_timeout=2,
        )

    assert "simulated DRM startup failure" in caplog.text


def test_background_syntax_tracks_mpv_037_api_change():
    assert _background_commands("0.37.0") == [
        ["set_property", "background", "#000000"],
    ]
    assert _background_commands("mpv 0.37.0") == _background_commands("0.37.0")
    assert _background_commands("0.38.0") == [
        ["set_property", "background", "color"],
        ["set_property", "background-color", "#000000"],
    ]
    assert _background_commands("0.40.0-3+deb13u1") == _background_commands("0.38.0")
    assert _background_commands("mpv v0.40.0") == _background_commands("0.38.0")
    with pytest.raises(MPVError, match="0.37 or newer"):
        _background_commands("0.36.0")
