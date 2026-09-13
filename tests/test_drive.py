"""Exercise OAuth lifecycle and Drive I/O at the external service boundary."""

from unittest.mock import Mock

import httplib2
import pytest
from googleapiclient.http import HttpRequest


@pytest.mark.parametrize("state", ["saved", "expired", "first_run"])
def test_authentication_reuses_refreshes_or_creates_token(app, monkeypatch, state):
    drive = app.drive
    token = drive.GOOGLE_TOKEN_FILE
    creds = Mock(valid=state == "saved", expired=state == "expired", refresh_token="test-refresh")
    creds.to_json.return_value = '{"token": "new-test-token"}'
    if state != "first_run":
        token.write_text('{"token": "saved-test-token"}')
    load = Mock(return_value=creds)
    flow = Mock()
    flow.run_local_server.return_value = creds
    authorize = Mock(return_value=flow)
    build = Mock()
    monkeypatch.setattr(drive.Credentials, "from_authorized_user_file", load)
    monkeypatch.setattr(drive.InstalledAppFlow, "from_client_secrets_file", authorize)
    monkeypatch.setattr(drive, "build", build)

    assert drive.get_drive_service() is build.return_value
    build.assert_called_once()
    transport = build.call_args.kwargs["http"]
    assert transport.credentials is creds
    assert transport.http.timeout == drive.NETWORK_TIMEOUT
    if state == "first_run":
        load.assert_not_called()
        authorize.assert_called_once_with(drive.GOOGLE_CREDENTIALS_FILE, drive.GOOGLE_SCOPES)
        flow.run_local_server.assert_called_once_with(port=8080, open_browser=False, timeout_seconds=60)
    else:
        load.assert_called_once_with(token, drive.GOOGLE_SCOPES)
        authorize.assert_not_called()
    if state == "expired":
        creds.refresh.assert_called_once()
    else:
        creds.refresh.assert_not_called()
    expected = "saved-test-token" if state == "saved" else "new-test-token"
    assert token.read_text() == f'{{"token": "{expected}"}}'


def test_download_writes_all_chunks(app, tmp_path, monkeypatch):
    # Use the real Google downloader with an in-memory HTTP transport.
    transport = Mock()
    transport.request.side_effect = [
        (httplib2.Response({"status": "206", "content-range": "bytes 0-2/6"}), b"abc"),
        (httplib2.Response({"status": "206", "content-range": "bytes 3-5/6"}), b"def"),
    ]
    request = HttpRequest(transport, lambda response, content: content, "https://example.invalid/photo")
    service = Mock()
    service.files.return_value.get_media.return_value = request
    monkeypatch.setattr(app.drive, "get_drive_service", lambda: service)
    destination = tmp_path / "photo.jpg.part"

    app.drive.download_photo("photo-id", destination)

    assert destination.read_bytes() == b"abcdef"
    assert transport.request.call_count == 2
    service.files.return_value.get_media.assert_called_once_with(fileId="photo-id")


def test_album_listing_paginates_root_and_children_and_ignores_loose_and_nested_photos(app, monkeypatch):
    service = Mock()
    dates = {"createdTime": "2025-01-01T00:00:00Z", "modifiedTime": "2026-09-12T00:00:00Z"}
    folder = lambda file_id: {"id": file_id, "name": file_id, "mimeType": "application/vnd.google-apps.folder", **dates}
    photo = lambda file_id: {"id": file_id, "name": file_id + ".jpg", "mimeType": "image/jpeg", **dates}
    service.files.return_value.list.return_value.execute.side_effect = [
        {"files": [photo("loose"), folder("kids")], "nextPageToken": "root-next"},
        {"files": [photo("one"), folder("nested"), {"id": "svg", "name": "logo.svg", "mimeType": "image/svg+xml"}], "nextPageToken": "kids-next"},
        {"files": [photo("two")]},
        {"files": [folder("empty")]},
        {"files": []},
    ]
    monkeypatch.setattr(app.drive, "get_drive_service", lambda: service)
    assert app.drive.list_albums("root") == [
        {"id": "kids", "name": "kids", "photos": [photo("one"), photo("two")], **dates},
        {"id": "empty", "name": "empty", "photos": [], **dates},
    ]
    calls = service.files.return_value.list.call_args_list
    assert [call.kwargs["pageToken"] for call in calls] == [None, None, "kids-next", "root-next", None]
    assert all("md5Checksum" in call.kwargs["fields"] for call in calls)
    assert all("createdTime" in call.kwargs["fields"] and "modifiedTime" in call.kwargs["fields"] for call in calls)


def test_incomplete_drive_search_cannot_be_used_to_delete_cached_photos(app, monkeypatch):
    service = Mock()
    service.files.return_value.list.return_value.execute.return_value = {"files": [], "incompleteSearch": True}
    monkeypatch.setattr(app.drive, "get_drive_service", lambda: service)
    with pytest.raises(RuntimeError, match="incomplete"):
        app.drive.list_albums("root")
