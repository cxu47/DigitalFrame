"""Exercise browser form requests without a socket or running display."""

from html import escape

from fastapi.testclient import TestClient
import pytest

from client.control.app import create_app
from client.settings import INTEGER_ERROR, RuntimeSettings
from client.update import UpdateSnapshot


@pytest.fixture
def panel():
    settings = RuntimeSettings(5)
    with TestClient(create_app(settings)) as browser:
        yield settings, browser


def test_page_is_self_contained_and_loads_from_any_directory(panel, monkeypatch, tmp_path):
    settings, browser = panel
    monkeypatch.chdir(tmp_path)
    response = browser.get("/")
    assert response.status_code == 200
    assert response.headers["content-type"].startswith("text/html")
    assert response.headers["cache-control"] == "no-store"
    assert 'value="5"' in response.text
    assert 'method="post" action="/settings"' in response.text
    assert 'aria-describedby="error"' in response.text
    assert response.text.index('</form>') < response.text.index('<p id="error"')
    for unexpected in ("<script", "<style", "<link", "https://", "GOOGLE_", "SECRETS"):
        assert unexpected not in response.text
    assert settings.display_seconds == 5


@pytest.mark.parametrize("value,expected", [("1", 1), ("10", 10), (" 5 ", 5), ("005", 5)])
def test_valid_form_redirects_and_refresh_does_not_resubmit(panel, value, expected):
    settings, browser = panel
    response = browser.post("/settings", data={"display_seconds": value}, follow_redirects=False)
    assert response.status_code == 303
    assert response.headers["location"] == "/"
    assert settings.display_seconds == expected
    assert f'value="{expected}"' in browser.get("/").text
    settings.set_display_seconds(7)
    assert 'value="7"' in browser.get("/").text


@pytest.mark.parametrize("value", [None, "", " ", "abc", "5.0", "1.5", "1/2", "1e3", "+5",
                                  "0", "-1", "true", "null", "9" * 5000, '<script>"&</script>'])
def test_invalid_form_shows_error_and_allows_correction(panel, value):
    settings, browser = panel
    response = browser.post("/settings", data={} if value is None else {"display_seconds": value})
    assert response.status_code == 422
    assert response.headers["content-type"].startswith("text/html")
    assert INTEGER_ERROR in response.text
    assert f'value="{escape(value or "", quote=True)}"' in response.text
    assert "Current duration: 5 seconds" in response.text
    assert settings.display_seconds == 5
    assert browser.get("/").status_code == 200
    assert browser.post("/settings", data={"display_seconds": "8"}).status_code == 200
    assert settings.display_seconds == 8


@pytest.mark.parametrize("kwargs,status", [
    ({"json": {"display_seconds": 10}}, 415),
    ({"content": "broken", "headers": {"content-type": "multipart/form-data"}}, 400),
    ({"files": {"display_seconds": ("value.txt", b"10")}}, 422),
])
def test_bad_request_shapes_are_html_errors_and_do_not_crash(panel, kwargs, status):
    settings, browser = panel
    response = browser.post("/settings", **kwargs)
    assert response.status_code == status
    assert response.headers["content-type"].startswith("text/html")
    assert '<p id="error"' in response.text
    assert settings.display_seconds == 5
    assert browser.post("/settings", data={"display_seconds": "8"}).status_code == 200


def test_multipart_text_field_is_supported(panel):
    settings, browser = panel
    response = browser.post("/settings", files={"display_seconds": (None, "10")})
    assert response.status_code == 200
    assert settings.display_seconds == 10


def test_folder_form_includes_empty_albums_escapes_names_and_tracks_sync_changes():
    folders = ['kids', 'summer', 'empty', 'All', '<fun & "things">']
    settings = RuntimeSettings(5, folders=lambda: folders)
    with TestClient(create_app(settings)) as browser:
        page = browser.get('/').text
        assert '<option value="" selected>All</option>' in page
        assert '<option value="empty">empty</option>' in page
        assert '&lt;fun &amp; &quot;things&quot;&gt;' in page
        result = browser.post('/folder', data={'folder': 'kids'}, follow_redirects=False)
        assert result.status_code == 303
        assert settings.selected_folder == 'kids'
        assert '<option value="kids" selected>kids</option>' in browser.get('/').text
        assert browser.post('/folder', data={'folder': '../outside'}).status_code == 422
        assert browser.post('/folder', json={'folder': 'summer'}).status_code == 415
        invalid = browser.post('/folder', files={'folder': ('name.txt', b'kids')})
        assert invalid.status_code == 422
        assert 'Choose an existing folder or All.' in invalid.text
        assert settings.selected_folder == 'kids'
        folders.append('new album')
        assert 'new album' in browser.get('/').text
        folders.remove('kids')
        assert '<option value="" selected>All</option>' in browser.get('/').text
        assert settings.selected_folder is None
        browser.post('/folder', data={'folder': 'All'})
        assert settings.selected_folder == 'All'  # A real folder named All is distinct.
        browser.post('/folder', data={'folder': ''})
        assert settings.selected_folder is None
        browser.post('/folder', data={'folder': 'summer'})
        assert RuntimeSettings(5, folders=lambda: folders).selected_folder is None


def test_month_form_selects_multiple_buckets_and_overrides_folder_mode():
    months = ["2026-09", "2026-08", "2025-12"]
    settings = RuntimeSettings(
        5, folders=lambda: ["kids", "summer"], months=lambda: months)
    with TestClient(create_app(settings)) as browser:
        page = browser.get("/").text
        assert 'Photo folder <small aria-label="Active viewing mode">✓ Active</small>' in page
        assert 'value="2026-09">09-2026' in page
        assert 'value="2026-08">08-2026' in page

        response = browser.post(
            "/months",
            data={"month": ["2026-09", "2025-12"]},
            follow_redirects=False,
        )
        assert response.status_code == 303
        assert settings.view_mode == "months"
        assert settings.selected_months == ("2026-09", "2025-12")
        page = browser.get("/").text
        assert 'Photo months <small aria-label="Active viewing mode">✓ Active</small>' in page
        assert 'value="2026-09" checked>09-2026' in page
        assert 'value="2025-12" checked>12-2025' in page

        assert browser.post("/months", data={}).status_code == 422
        assert browser.post("/months", data={"month": "2024-01"}).status_code == 422
        assert browser.post("/months", json={"month": ["2026-08"]}).status_code == 415
        assert settings.view_mode == "months"

        browser.post("/folder", data={"folder": "summer"})
        assert settings.view_mode == "folder"
        assert settings.selected_folder == "summer"
        assert settings.selected_months == ("2026-09", "2025-12")
        page = browser.get("/").text
        assert 'Photo folder <small aria-label="Active viewing mode">✓ Active</small>' in page
        assert 'value="2026-09" checked>09-2026' in page


class FakeUpdater:
    def __init__(self):
        self.state = UpdateSnapshot()
        self.checked = 0
        self.applied = 0

    def snapshot(self):
        return self.state

    def check(self):
        self.checked += 1
        self.state = UpdateSnapshot("available", "Update available: aaa → bbb.", True)

    def apply(self):
        self.applied += 1
        self.state = UpdateSnapshot("updated", "Updated to bbb. DigitalFrame is restarting now.")
        return self.state


def test_update_requires_explicit_token_protected_check_before_showing_install():
    import re

    updater = FakeUpdater()
    settings = RuntimeSettings(5)
    restarts = []
    with TestClient(create_app(
            settings, updater=updater, request_restart=lambda: restarts.append(True))) as browser:
        initial = browser.get("/").text
        assert 'action="/update/check"' in initial
        assert 'action="/update/apply"' not in initial
        token = re.search(r'name="update_token" value="([^"]+)"', initial)[1]

        assert browser.post("/update/check", data={"update_token": "wrong"}).status_code == 403
        assert browser.post(
            "/update/check", data={"update_token": token},
            headers={"origin": "https://evil.invalid"},
        ).status_code == 403
        assert updater.checked == 0

        checked = browser.post(
            "/update/check", data={"update_token": token}, follow_redirects=False,
        )
        assert checked.status_code == 303
        assert checked.headers["location"] == "/"
        available = browser.get("/").text
        assert "Update available: aaa → bbb." in available
        assert 'action="/update/apply"' in available
        assert updater.checked == 1

        applied = browser.post(
            "/update/apply", data={"update_token": token}, follow_redirects=False,
        )
        assert applied.status_code == 200
        assert "Updated to bbb. DigitalFrame is restarting now." in applied.text
        assert 'action="/update/apply"' not in browser.get("/").text
        assert updater.applied == 1
        assert restarts == [True]


def test_failed_update_does_not_restart_process():
    import re

    class FailedUpdater(FakeUpdater):
        def apply(self):
            self.applied += 1
            self.state = UpdateSnapshot("error", "The update was stopped safely.")
            return self.state

    updater = FailedUpdater()
    updater.state = UpdateSnapshot("available", "Update available.", True)
    restarts = []
    with TestClient(create_app(
            RuntimeSettings(5), updater=updater,
            request_restart=lambda: restarts.append(True))) as browser:
        initial = browser.get("/").text
        token = re.search(r'name="update_token" value="([^"]+)"', initial)[1]
        response = browser.post(
            "/update/apply", data={"update_token": token}, follow_redirects=False,
        )

    assert response.status_code == 303
    assert updater.applied == 1
    assert restarts == []
