"""Update checks are explicit, fixed to release/2.x, and fast-forward only."""

import os
from pathlib import Path
import shutil
import subprocess
from types import SimpleNamespace

from client.update import UpdateManager, UpdateSnapshot


def _result(output, returncode=0):
    return SimpleNamespace(stdout=output, stderr="", returncode=returncode)


def test_manager_exposes_apply_only_for_a_clean_available_update(monkeypatch, tmp_path):
    manager = UpdateManager(tmp_path)
    monkeypatch.setattr(manager, "_run", lambda *_: _result(
        "state=available\ndirty=0\n"
        "local=1111111111111111111111111111111111111111\n"
        "remote=2222222222222222222222222222222222222222\n"
    ))
    checked = manager.check()
    assert checked == UpdateSnapshot(
        "available", "Update available: 111111111111 → 222222222222.", True
    )

    monkeypatch.setattr(manager, "_run", lambda *_: _result(
        "state=updated\n"
        "local=1111111111111111111111111111111111111111\n"
        "remote=2222222222222222222222222222222222222222\n"
    ))
    assert manager.apply() == UpdateSnapshot(
        "updated", "Updated to 222222222222. DigitalFrame is restarting now."
    )


def test_manager_blocks_dirty_or_diverged_checkouts(monkeypatch, tmp_path):
    manager = UpdateManager(tmp_path)
    monkeypatch.setattr(manager, "_run", lambda *_: _result(
        "state=available\ndirty=1\n"
        "local=1111111111111111111111111111111111111111\n"
        "remote=2222222222222222222222222222222222222222\n"
    ))
    assert manager.check().state == "dirty"
    assert not manager.snapshot().can_apply
    assert manager.apply().state == "blocked"

    monkeypatch.setattr(manager, "_run", lambda *_: _result(
        "state=diverged\ndirty=0\n"
        "local=1111111111111111111111111111111111111111\n"
        "remote=2222222222222222222222222222222222222222\n"
    ))
    assert manager.check().state == "diverged"
    assert not manager.snapshot().can_apply


def _git(directory, *args):
    return subprocess.run(
        ["git", *args], cwd=directory, check=True, capture_output=True, text=True,
    ).stdout.strip()


def test_shell_scripts_fetch_then_fast_forward_and_sync(tmp_path):
    source_deploy = Path(__file__).resolve().parents[1] / "deploy"
    remote = tmp_path / "remote.git"
    publisher = tmp_path / "publisher"
    checkout = tmp_path / "frame"
    remote.mkdir()
    publisher.mkdir()
    _git(remote, "init", "--bare")
    _git(publisher, "init", "-b", "release/2.x")
    _git(publisher, "config", "user.name", "DigitalFrame tests")
    _git(publisher, "config", "user.email", "tests@example.invalid")
    (publisher / "deploy").mkdir()
    for name in ("check-update.sh", "apply-update.sh"):
        shutil.copy2(source_deploy / name, publisher / "deploy" / name)
    (publisher / "version.txt").write_text("one\n")
    _git(publisher, "add", ".")
    _git(publisher, "commit", "-m", "initial")
    _git(publisher, "remote", "add", "origin", str(remote))
    _git(publisher, "push", "-u", "origin", "release/2.x")
    _git(tmp_path, "clone", "--branch", "release/2.x", str(remote), str(checkout))

    current = subprocess.run(
        [str(checkout / "deploy/check-update.sh")], cwd=checkout,
        check=True, capture_output=True, text=True,
    )
    assert "state=current" in current.stdout

    (publisher / "version.txt").write_text("two\n")
    _git(publisher, "add", "version.txt")
    _git(publisher, "commit", "-m", "update")
    _git(publisher, "push", "origin", "release/2.x")
    available = subprocess.run(
        [str(checkout / "deploy/check-update.sh")], cwd=checkout,
        check=True, capture_output=True, text=True,
    )
    assert "state=available" in available.stdout
    assert "dirty=0" in available.stdout

    uv = tmp_path / "fake-uv"
    uv.write_text("#!/bin/sh\nprintf '%s\\n' \"$*\" > \"$UV_LOG\"\n")
    uv.chmod(0o755)
    uv_log = tmp_path / "uv.log"
    environment = os.environ | {"UV_BIN": str(uv), "UV_LOG": str(uv_log)}
    applied = subprocess.run(
        [str(checkout / "deploy/apply-update.sh")], cwd=checkout, env=environment,
        check=True, capture_output=True, text=True,
    )
    assert "state=updated" in applied.stdout
    assert (checkout / "version.txt").read_text() == "two\n"
    assert uv_log.read_text().strip() == "sync --locked --no-dev"
    assert _git(checkout, "status", "--porcelain") == ""

    (publisher / "version.txt").write_text("three\n")
    _git(publisher, "add", "version.txt")
    _git(publisher, "commit", "-m", "second update")
    _git(publisher, "push", "origin", "release/2.x")
    (checkout / "local-note.txt").write_text("do not discard\n")
    dirty = subprocess.run(
        [str(checkout / "deploy/check-update.sh")], cwd=checkout,
        check=True, capture_output=True, text=True,
    )
    assert "state=available" in dirty.stdout
    assert "dirty=1" in dirty.stdout
    blocked = subprocess.run(
        [str(checkout / "deploy/apply-update.sh")], cwd=checkout, env=environment,
        check=False, capture_output=True, text=True,
    )
    assert blocked.returncode == 2
    assert "reason=dirty" in blocked.stdout
    assert (checkout / "version.txt").read_text() == "two\n"
    assert (checkout / "local-note.txt").read_text() == "do not discard\n"
