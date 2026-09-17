"""Integer boundaries and isolated, thread-safe runtime state."""

from concurrent.futures import ThreadPoolExecutor
import os
import subprocess
import sys

from dotenv import dotenv_values
import pytest

from client.settings import RuntimeSettings, SettingsPersistenceError, parse_display_seconds


@pytest.mark.parametrize("text,expected", [("1", 1), ("10", 10), (" 5 ", 5), ("005", 5)])
def test_integer_text(text, expected):
    assert parse_display_seconds(text) == expected


@pytest.mark.parametrize("text", [None, "", " ", "abc", "5.0", "1.5", "1/2", "1e3",
                                  "+5", "0", "-1", "true", "null", "５", "1_000", "9" * 5000])
def test_invalid_integer_text(text):
    with pytest.raises(ValueError, match="positive whole number"):
        parse_display_seconds(text)


@pytest.mark.parametrize("value", [True, False, 5.0, "5", None, 0, -1])
def test_service_rejects_invalid_values_without_mutation(value):
    settings = RuntimeSettings(5)
    with pytest.raises(ValueError):
        settings.set_display_seconds(value)
    assert settings.display_seconds == 5


def test_concurrent_updates_and_new_runtime_reset():
    settings = RuntimeSettings(5)

    def update(value):
        settings.set_display_seconds(value)
        assert type(settings.display_seconds) is int
        assert settings.display_seconds > 0

    with ThreadPoolExecutor(max_workers=4) as pool:
        list(pool.map(update, range(1, 100)))
    settings.set_display_seconds(20)
    assert settings.display_seconds == 20
    assert RuntimeSettings(5).display_seconds == 5


def test_snapshot_records_each_accepted_submission_only():
    settings = RuntimeSettings(5)
    assert settings.notification_snapshot() == ("Seconds per photo: 5", 0)
    settings.set_display_seconds(10)
    assert settings.notification_snapshot() == ("Seconds per photo: 10", 1)
    settings.set_display_seconds(10)
    assert settings.notification_snapshot() == ("Seconds per photo: 10", 2)
    with pytest.raises(ValueError):
        settings.set_display_seconds(1.5)
    assert settings.notification_snapshot() == ("Seconds per photo: 10", 2)


def test_duration_and_folder_persist_across_runtime_instances(tmp_path):
    state = tmp_path / ".env"
    state.write_text("DISPLAY_SECONDS=5\nSELECTED_FOLDER=\nKEEP_ME=unchanged\n")
    folders = lambda: ["kids", "summer"]
    settings = RuntimeSettings(5, folders=folders, env_path=state)

    settings.set_display_seconds(12)
    settings.set_folder("summer")

    saved = dotenv_values(state)
    restored = RuntimeSettings(
        int(saved["DISPLAY_SECONDS"]), folders=folders,
        selected_folder=saved["SELECTED_FOLDER"], env_path=state)
    assert restored.display_seconds == 12
    assert restored.selected_folder == "summer"
    assert saved["KEEP_ME"] == "unchanged"


def test_missing_saved_folder_falls_back_to_all_and_updates_env(tmp_path):
    state = tmp_path / ".env"
    state.write_text("DISPLAY_SECONDS=7\nSELECTED_FOLDER=gone\n")

    restored = RuntimeSettings(
        7, folders=lambda: ["kids"], selected_folder="gone", env_path=state)

    assert restored.display_seconds == 7
    assert restored.selected_folder is None
    assert dotenv_values(state)["SELECTED_FOLDER"] == ""


def test_failed_env_write_does_not_apply_setting(monkeypatch, tmp_path):
    settings = RuntimeSettings(5, folders=lambda: ["kids"], env_path=tmp_path / ".env")
    monkeypatch.setattr("client.settings.set_key", lambda *args, **kwargs: (_ for _ in ()).throw(
        OSError("read only")))

    with pytest.raises(SettingsPersistenceError, match=".env is writable"):
        settings.set_display_seconds(12)
    with pytest.raises(SettingsPersistenceError, match=".env is writable"):
        settings.set_folder("kids")

    assert settings.display_seconds == 5
    assert settings.selected_folder is None


@pytest.mark.parametrize("name,value,valid", [
    ("DISPLAY_SECONDS", "5", True), ("DISPLAY_SECONDS", "5.0", False),
    ("DISPLAY_SECONDS", "0.2", False), ("DISPLAY_SECONDS", "0", False),
    ("DISPLAY_SECONDS", "-1", False), ("DISPLAY_SECONDS", "abc", False),
    ("DISPLAY_SECONDS", "", False), ("DISPLAY_SECONDS", None, True),
    ("CONTROL_PORT", "65535", True), ("CONTROL_PORT", "0", False),
    ("CONTROL_PORT", "65536", False), ("CONTROL_PORT", "8000.0", False),
    ("CONTROL_HOST", "", False),
    ("CONTROL_URL_DISPLAY_SECONDS", "30", True),
    ("CONTROL_URL_DISPLAY_SECONDS", "0", True),
    ("CONTROL_URL_DISPLAY_SECONDS", "-1", False),
    ("CONTROL_URL_DISPLAY_SECONDS", "1.5", False),
    ("CONTROL_URL_DISPLAY_SECONDS", "abc", False),
    ("CONTROL_URL_DISPLAY_SECONDS", "", False),
    ("CONTROL_URL_DISPLAY_SECONDS", None, True),
    ("CACHE_MAX_WIDTH", "1600", True), ("CACHE_MAX_WIDTH", "0", False),
    ("CACHE_MAX_WIDTH", "1600.5", False),
    ("CACHE_MAX_HEIGHT", "900", True), ("CACHE_MAX_HEIGHT", "16385", False),
    ("OTHER_IMAGE_QUALITY", "85", True), ("OTHER_IMAGE_QUALITY", "96", False),
    ("IPHONE_JPEG_QUALITY", "75", True), ("IPHONE_JPEG_QUALITY", "0", False),
])
def test_configuration_in_fresh_interpreter(name, value, valid):
    env = os.environ.copy()
    if value is None:
        env.pop(name, None)
    else:
        env[name] = value
    result = subprocess.run(
        [sys.executable, "-c", "from client import config; assert isinstance(config.DISPLAY_SECONDS, int); "
         "assert isinstance(config.IDLE_SECONDS, float); assert isinstance(config.SYNC_INTERVAL, float); "
         "assert isinstance(config.CONTROL_URL_DISPLAY_SECONDS, int); "
         "assert isinstance(config.CONTROL_PORT, int); assert config.CONTROL_HOST; "
         "assert isinstance(config.CACHE_MAX_WIDTH, int); "
         "assert isinstance(config.CACHE_MAX_HEIGHT, int); "
         "assert isinstance(config.OTHER_IMAGE_QUALITY, int); "
         "assert isinstance(config.IPHONE_JPEG_QUALITY, int); "
         "assert isinstance(config.SYNC_INTERVAL, float)"],
        env=env, capture_output=True, text=True, timeout=10,
    )
    assert (result.returncode == 0) is valid, result.stderr
    if not valid:
        assert name in result.stderr


@pytest.mark.parametrize('name', ['IDLE_SECONDS', 'SYNC_INTERVAL', 'NETWORK_TIMEOUT'])
@pytest.mark.parametrize('value', ['-1', '0', 'nan', 'inf', '-inf', '0.0001'])
def test_invalid_intervals_fail_validation(monkeypatch, name, value):
    from client import config
    monkeypatch.setenv(name, value)
    with pytest.raises(ValueError, match=name):
        getattr(config, name)
