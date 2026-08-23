from pathlib import Path
from fastapi import FastAPI, File, UploadFile, HTTPException
from fastapi.responses import FileResponse


app = FastAPI()

PHOTO_DIR = Path("server/photos")
PHOTO_DIR.mkdir(parents=True, exist_ok=True)


@app.get("/health")
def health():
    return {"status": "ok"}


@app.post("/photos")
async def upload_photo(file: UploadFile = File(...)):
    destination = PHOTO_DIR / file.filename

    contents = await file.read()

    with open(destination, "wb") as output:
        output.write(contents)

    return {
        "filename": file.filename,
        "status": "uploaded",
    }

@app.get("/photos")
def list_photos():
    photos = [
        file.name
        for file in PHOTO_DIR.iterdir()
        if file.is_file() and file.name != ".gitkeep"
    ]

    return {"photos": photos}

@app.get("/photos/{filename}")
def get_photo(filename: str):
    path = PHOTO_DIR / filename
    if not path.exists():
        raise HTTPException(
            status_code=404,
            detail="Photo not found",
        )
    return FileResponse(path)
