import logging

from client.storage import google_drive


def test_refresh_credentials_logs_at_debug(
    tmp_path,
    monkeypatch,
    caplog,
):
    token_file = tmp_path / "google_token.json"
    token_file.write_text("{}")

    class FakeCredentials:
        valid = False
        expired = True
        refresh_token = "private-refresh-token"

        def refresh(self, request):
            pass

        def to_json(self):
            return "{}"

    monkeypatch.setattr(google_drive, "GOOGLE_TOKEN_FILE", token_file)
    monkeypatch.setattr(
        google_drive.Credentials,
        "from_authorized_user_file",
        lambda token_path, scopes: FakeCredentials(),
    )
    monkeypatch.setattr(
        google_drive,
        "build",
        lambda *args, **kwargs: object(),
    )

    with caplog.at_level(logging.DEBUG, logger=google_drive.__name__):
        google_drive.get_drive_service()

    refresh_record = next(
        record
        for record in caplog.records
        if record.getMessage() == "Refreshing Google Drive credentials"
    )
    assert refresh_record.levelno == logging.DEBUG
    assert all(
        "private-refresh-token" not in message
        for message in caplog.messages
    )


def test_list_photos_filters_non_images_and_logs_boundaries(
    monkeypatch,
    caplog,
):
    folder_id = "private-folder-id"

    class FakeListRequest:
        def execute(self):
            return {
                "files": [
                    {
                        "id": "image-id",
                        "name": "photo.jpg",
                        "mimeType": "image/jpeg",
                    },
                    {
                        "id": "document-id",
                        "name": "notes.txt",
                        "mimeType": "text/plain",
                    },
                ]
            }

    class FakeFiles:
        def list(self, **kwargs):
            assert folder_id in kwargs["q"]
            return FakeListRequest()

    class FakeService:
        def files(self):
            return FakeFiles()

    monkeypatch.setattr(
        google_drive,
        "get_drive_service",
        lambda: FakeService(),
    )

    with caplog.at_level(logging.DEBUG, logger=google_drive.__name__):
        photos = google_drive.list_photos(folder_id)

    assert [photo["name"] for photo in photos] == ["photo.jpg"]
    assert "Requesting Google Drive photo listing" in caplog.messages
    assert (
        "Google Drive photo listing returned 1 images" in caplog.messages
    )
    assert all(folder_id not in message for message in caplog.messages)
    assert all("image-id" not in message for message in caplog.messages)


def test_download_photo_logs_boundaries_without_file_id(
    tmp_path,
    monkeypatch,
    caplog,
):
    file_id = "private-file-id"
    destination = tmp_path / "photo.jpg.part"

    class FakeFiles:
        def get_media(self, fileId):
            assert fileId == file_id
            return object()

    class FakeService:
        def files(self):
            return FakeFiles()

    class FakeDownloader:
        def __init__(self, output_file, request):
            output_file.write(b"image")

        def next_chunk(self):
            return None, True

    monkeypatch.setattr(
        google_drive,
        "get_drive_service",
        lambda: FakeService(),
    )
    monkeypatch.setattr(
        google_drive,
        "MediaIoBaseDownload",
        FakeDownloader,
    )

    with caplog.at_level(logging.DEBUG, logger=google_drive.__name__):
        google_drive.download_photo(file_id, destination)

    assert destination.read_bytes() == b"image"
    assert "Starting Google Drive media download" in caplog.messages
    assert "Google Drive media download completed" in caplog.messages
    assert all(file_id not in message for message in caplog.messages)
