import httpx

SERVER_URL = "http://127.0.0.1:8000"


def get_photos():
    response = httpx.get(f"{SERVER_URL}/photos")
    response.raise_for_status()

    return response.json()["photos"]


if __name__ == "__main__":
    photos = get_photos()
    print(photos)
