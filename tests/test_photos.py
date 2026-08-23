from fastapi.testclient import TestClient
from server.main import app, PHOTO_DIR

client = TestClient(app)


def test_upload_photo(tmp_path, monkeypatch):
    monkeypatch.setattr("server.main.PHOTO_DIR", tmp_path)

    response = client.post(
        "/photos",
        files={"file": ("test.jpg", b"fake image data", "image/jpeg")},
    )

    assert response.status_code == 200
    assert response.json()["filename"] == "test.jpg"
    assert (tmp_path / "test.jpg").exists()


def test_list_photos(tmp_path, monkeypatch):
    monkeypatch.setattr("server.main.PHOTO_DIR", tmp_path)

    (tmp_path / "one.jpg").write_bytes(b"one")
    (tmp_path / "two.jpg").write_bytes(b"two")

    response = client.get("/photos")

    assert response.status_code == 200
    assert set(response.json()["photos"]) == {"one.jpg", "two.jpg"}


def test_get_photo(tmp_path, monkeypatch):
    monkeypatch.setattr("server.main.PHOTO_DIR", tmp_path)

    photo = tmp_path / "test.jpg"
    photo.write_bytes(b"fake image data")

    response = client.get("/photos/test.jpg")

    assert response.status_code == 200
    assert response.content == b"fake image data"
