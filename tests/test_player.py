"""Exercise the real JSON IPC transport without requiring a display or mpv."""

import json

import pytest

from client.player import MPVError, MPVPlayer, _ass_text, _background_commands


FAKE_MPV = r'''#!/usr/bin/env python3
import json
import os
import socket
import sys

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
    if isinstance(command, dict) and "_name" in command:
        connection.sendall((json.dumps({"request_id": request["request_id"], "error": "invalid parameter"}) + "\n").encode())
        continue
    data = "mpv 0.37.0" if name == "get_property" else None
    connection.sendall((json.dumps({"request_id": request["request_id"], "error": "success", "data": data}) + "\n").encode())
    if name == "loadfile":
        entry += 1
        connection.sendall((json.dumps({"event": "start-file", "playlist_entry_id": entry}) + "\n").encode())
        if "bad" in command[1]:
            event = {"event": "end-file", "reason": "error", "playlist_entry_id": entry, "file_error": "broken image"}
        else:
            event = {"event": "file-loaded"}
        connection.sendall((json.dumps(event) + "\n").encode())
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


def test_ass_overlay_text_is_escaped():
    assert _ass_text("{a}\\b\nc") == r"\{a\}\\b\Nc"


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
    with pytest.raises(MPVError, match="0.37 or newer"):
        _background_commands("0.36.0")
